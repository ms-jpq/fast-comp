from os.path import dirname, join, realpath

__kok__ = dirname(dirname(realpath(__file__)))
__base__ = dirname(dirname(dirname(__kok__)))
__config__ = join(__base__, "config")
__artifacts__ = join(__base__, "artifacts")
__log_file__ = join(__base__, "logs", "kok.log")
__debug_db__ = join(__artifacts__, "debug.sqlite")

settings_json = join(__config__, "config.json")

module_entry_point = "main"

load_hierarchy = (dirname(__base__),)

conf_var_name = "kok_settings"
conf_var_name_private = "kok_settings_private"
buf_var_name = "buflocal_kok"
