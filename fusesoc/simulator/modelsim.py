import os
from .simulator import Simulator
from fusesoc.config import Config
from fusesoc.utils import Launcher, pr_warn

VPI_MAKE_HEADER ="""#Generated by FuseSoC
CC ?= gcc
CFLAGS := -c -std=c99 -fPIC -fno-stack-protector -g -m32

LD ?= ld
LDFLAGS := -shared -E -melf_i386

RM ?= rm
INCS := -I{inc}

all: {modules}

clean: {clean_targets}
"""

VPI_MAKE_SECTION = """
{name}_ROOT := {root}
{name}_OBJS := {objs}
{name}_LIBS := {libs}
{name}_INCS := $(INCS) {incs}

$({name}_OBJS): %.o : $({name}_ROOT)/%.c
	$(CC) $(CFLAGS) $({name}_INCS) $<

{name}: $({name}_OBJS)
	$(LD) $(LDFLAGS) -o $@ $? $({name}_LIBS)

clean_{name}:
	$(RM) $({name}_OBJS) {name}
"""

class Modelsim(Simulator):

    TOOL_NAME = 'MODELSIM'
    def __init__(self, system):

        self.vlog_options = []
        self.vsim_options = []
        self.run_default_args = ['-quiet', '-c', '-do', 'run -all']

        if system.modelsim is not None:
            self.vlog_options = system.modelsim.vlog_options
            self.vsim_options = system.modelsim.vsim_options
            if system.modelsim.run_default_args:
                self.run_default_args = system.modelsim.run_default_args
        super(Modelsim, self).__init__(system)
        self.model_tech = os.getenv('MODEL_TECH')
        if not self.model_tech:
            raise RuntimeError("Environment variable MODEL_TECH was not found. It should be set to <modelsim install path>/bin")

    def _write_build_rtl_tcl_file(self, tcl_main):
        tcl_build_rtl  = open(os.path.join(self.sim_root, "fusesoc_build_rtl.tcl"), 'w')

        (src_files, incdirs) = self._get_fileset_files(['sim', 'modelsim'])
        vlog_include_dirs = ['+incdir+'+d.replace('\\','/') for d in incdirs]

        libs = []
        for f in src_files:
            if not f.logical_name:
                f.logical_name = 'work'
            if not f.logical_name in libs:
                tcl_build_rtl.write("vlib {}\n".format(f.logical_name))
                libs.append(f.logical_name)
            if f.file_type in ["verilogSource",
		               "verilogSource-95",
		               "verilogSource-2001",
		               "verilogSource-2005"]:
                cmd = 'vlog'
                args = self.vlog_options[:]
                args += vlog_include_dirs
            elif f.file_type in ["systemVerilogSource",
			         "systemVerilogSource-3.0",
			         "systemVerilogSource-3.1",
			         "systemVerilogSource-3.1a"]:
                cmd = 'vlog'
                args = self.vlog_options[:]
                args += ['-sv']
                args += vlog_include_dirs
            elif f.file_type == 'vhdlSource':
                cmd = 'vcom'
                args = []
            elif f.file_type == 'vhdlSource-87':
                cmd = 'vcom'
                args = ['-87']
            elif f.file_type == 'vhdlSource-93':
                cmd = 'vcom'
                args = ['-93']
            elif f.file_type == 'vhdlSource-2008':
                cmd = 'vcom'
                args = ['-2008']
            elif f.file_type == 'tclSource':
                cmd = None
                tcl_main.write("do {}\n".format(f.name))
            elif f.file_type == 'user':
                cmd = None
            else:
                _s = "{} has unknown file type '{}'"
                pr_warn(_s.format(f.name,
                                  f.file_type))
                cmd = None
            if cmd:
                if not Config().verbose:
                    args += ['-quiet']
                args += ['-work', f.logical_name]
                args += [f.name.replace('\\','/')]
                tcl_build_rtl.write("{} {}\n".format(cmd, ' '.join(args)))

    def _write_vpi_makefile(self):
        vpi_make = open(os.path.join(self.sim_root, "Makefile"), 'w')
        _vpi_inc = self.model_tech+'/../include'
        _modules = [m['name'] for m in self.vpi_modules]
        _clean_targets = ' '.join(["clean_"+m for m in _modules])
        _s = VPI_MAKE_HEADER.format(inc=_vpi_inc,
                                    modules = ' '.join(_modules),
                                    clean_targets = _clean_targets)
        vpi_make.write(_s)

        for vpi_module in self.vpi_modules:
            _name = vpi_module['name']
            _root = vpi_module['root']
            _objs = [os.path.splitext(os.path.basename(s))[0]+'.o' for s in vpi_module['src_files']]
            _libs = vpi_module['libs']
            _incs = ['-I'+d for d in vpi_module['include_dirs']]
            _s = VPI_MAKE_SECTION.format(name=_name,
                                         root=_root,
                                         objs=' '.join(_objs),
                                         libs=' '.join(_libs),
                                         incs=' '.join(_incs))
            vpi_make.write(_s)

        vpi_make.close()

    def configure(self, args):
        super(Modelsim, self).configure(args)
        tcl_main = open(os.path.join(self.sim_root, "fusesoc_main.tcl"), 'w')
        tcl_main.write("do fusesoc_build_rtl.tcl\n")

        self._write_build_rtl_tcl_file(tcl_main)
        if self.vpi_modules:
            self._write_vpi_makefile()
            tcl_main.write("make\n")
        tcl_main.close()

    def build(self):
        super(Modelsim, self).build()
        args = ['-c', '-do', 'do fusesoc_main.tcl; exit']
        Launcher(self.model_tech+'/vsim', args,
                 cwd      = self.sim_root,
                 errormsg = "Failed to build simulation model. Log is available in '{}'".format(os.path.join(self.sim_root, 'transcript'))).run()

    def run(self, args):
        super(Modelsim, self).run(args)

        #FIXME: Handle failures. Save stdout/stderr
        vpi_options = []
        for vpi_module in self.vpi_modules:
            vpi_options += ['-pli', vpi_module['name']]

        args = self.run_default_args
        args += self.vsim_options
        args += vpi_options
        args += [self.toplevel]

        # Plusargs
        for key, value in self.plusarg.items():
            args += ['+{}={}'.format(key, value)]
        #Top-level parameters
        for key, value in self.vlogparam.items():
            args += ['-g{}={}'.format(key, value)]

        Launcher(self.model_tech+'/vsim', args,
                 cwd      = self.sim_root,
                 errormsg = "Simulation failed. Simulation log is available in '{}'".format(os.path.join(self.sim_root, 'transcript'))).run()

        super(Modelsim, self).done(args)
