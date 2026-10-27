"""Build compiler-generated Python in an isolated FreeCAD document."""


def build_cad(source, title):
    import FreeCAD as App

    code = compile(source, "<PyOpticL schematic>", "exec")
    previous = App.ActiveDocument.Name if App.ActiveDocument else None
    document = App.newDocument("OpticalLayout")
    try:
        document.Label = title
        namespace = {"__name__": "pyopticl_schematic_generated"}
        exec(code, namespace)
        namespace["build_layout"]()
        document.recompute()
        if App.GuiUp:
            import FreeCADGui as Gui

            view = Gui.activeDocument().activeView()
            view.viewAxonometric()
            view.fitAll()
    except Exception:
        App.closeDocument(document.Name)
        if previous and App.getDocument(previous):
            App.setActiveDocument(previous)
        raise
    return document
