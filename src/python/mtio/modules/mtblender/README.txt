Had to rewrite this from scratch to support a wider range of blender versions.
This is now targeting versions 3.4 -4.0, while being developed on 4.0.

Before using this, you will want to run the following command in Blender's Console in the Scripting Tab:

import pip
pip.main(['install', 'pyyaml', 'ruamel.yaml', 'numpy', 'pyglm==2.7.0', 'ptvsd', 'Pillow', '--user'])

After that restart Blender.

To install, copy the umvc3_model_importer folder in your Blender plugins folder located at \AppData\Roaming\Blender Foundation\Blender\X\scripts\addons with X being your version number.
This version incorporates the model importer and exporter into the UI.


Some features are still incomplete.
