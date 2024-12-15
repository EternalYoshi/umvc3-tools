from . import modules
from . import mtlib
import properties

classes = [
    #modules.blender_plugin,
    modules.model_import.SUB_PT_Model_Import,    
    modules.model_import.SUB_PT_MOD_OT_import,
    modules.model_import.SUB_OP_MOD_ImportModelPath,
    modules.model_import.SUB_PT_MOD_OT_Choose_Metadata_YML,
    modules.anim_import.SUB_PT_Anim_Import,
    modules.anim_import.SUB_OP_anim_import,
    modules.anim_import.SUB_PT_MOD_OT_Choose_Anim_Metadata_YML,
    modules.anim_import.SUB_OP_ADD_JOINT_TWOFIFTYFIVE,
    modules.anim_export.SUB_PT_Anim_Export,
    modules.anim_export.SUB_OP_anim_export,
    modules.anim_export.SUB_PT_MOD_OT_Choose_Anim_Export_Metadata_YML,
    modules.model_export.SUB_PT_Model_Export,
    modules.model_export.SUB_PT_MOD_OT_export,
    modules.model_export.SUB_OP_MOD_ExportModelPath,
    modules.model_export.SUB_PT_MOD_OT_Choose_Metadata_For_Export_YML,
    modules.model_export.SUB_PT_MOD_OT_Choose_MRL_YML,
    mtlib.properties.ModelImportProperties
    
]