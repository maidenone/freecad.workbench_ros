import FreeCAD as fc

import FreeCADGui as fcgui

from ..gui_utils import tr


class _NewWorkcellCommand:
    """The command definition to create a new Workcell object."""

    def GetResources(self):
        return {'Pixmap': 'workcell.svg',
                'Accel': 'N, W',
                'ToolTip': tr('Create a Workcell.')}

    def IsActive(self):
        return fc.activeDocument() is not None

    def Activated(self):
        doc = fc.activeDocument()
        doc.openTransaction('Create Workcell')
        fcgui.doCommand('')
        fcgui.addModule('freecad.workbench_ros.workcell')
        fcgui.doCommand("_workcell = freecad.workbench_ros.workcell.make_workcell('Workcell')")
        # fcgui.doCommand('FreeCADGui.ActiveDocument.setEdit(_workcell.Name)')
        doc.commitTransaction()
        doc.recompute()


fcgui.addCommand('NewWorkcell', _NewWorkcellCommand())
