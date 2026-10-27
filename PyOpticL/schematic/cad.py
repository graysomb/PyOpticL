"""Build compiler-generated Python in an isolated FreeCAD document."""


def generation_source(source, settings):
    """Keep the exported Python readable and reproduce the CAD button's plate."""
    if not settings["generate_baseplate"]:
        return source
    body, _ = source.rsplit("\nif __name__ == ", 1)
    options = {"thickness": settings["plate_thickness"], "margin": settings["plate_margin"]}
    return body + (
        "\n\nfrom PyOpticL.schematic.cad import add_baseplate\n"
        f"BASEPLATE = {options!r}\n"
        "_build_optical_layout = build_layout\n\n"
        "def build_layout():\n"
        "    layout = _build_optical_layout()\n"
        "    add_baseplate(layout, **BASEPLATE)\n"
        "    return layout\n\n"
        'if __name__ == "__main__":\n'
        "    build_layout()\n"
    )


def add_baseplate(layout, thickness=12.7, margin=15):
    """Machine catalog mounts at their real seats without shifting optical poses."""
    import FreeCAD as App
    from PyOpticL import attachments, machined_baseplate

    root = layout.get_object()
    inverse = root.Placement.inverse()
    seats = []
    for assembly in list(root.Children):
        if getattr(assembly.Proxy, "object_group", None) in ("beam_path", "baseplate"):
            continue
        supported = False
        for obj in (assembly, *machined_baseplate.descendants(assembly)):
            profile = attachments.profile(obj.Proxy) or attachments.integration_profile(obj.Proxy)
            if profile:
                contract = obj.Proxy.contract()
                frame = next(f for f in contract.frames if f.name == profile["seat_frame"])
                seat = (inverse * obj.Placement).multVec(App.Vector(*frame.position))
                seats.append(seat.z)
                supported = True
            elif hasattr(obj.Proxy, "contract") and obj.Proxy.contract().catalog_id == "displacement-pbs-holder":
                frame = next(f for f in obj.Proxy.contract().frames if f.name == "base_patch")
                seats.append((inverse * obj.Placement).multVec(App.Vector(*frame.position)).z)
                supported = True
        if not supported:
            raise ValueError(
                f"{assembly.Label}: no supported baseplate attachment. Select a mounted lab-catalog "
                "Part preset (such as POLARIS-K05VS2 or POLARIS-K05T6), or turn off Baseplate."
            )
    if not seats:
        raise ValueError("A baseplate requires at least one supported mounted component.")
    top = max(seats)
    for obj in machined_baseplate.descendants(root):
        if (getattr(obj.Proxy, "object_group", None) == "beam_path"
                and hasattr(obj, "Shape") and not obj.Shape.isNull()):
            shape = obj.Shape.copy()
            shape.Placement = inverse * obj.Placement
            if top >= shape.BoundBox.ZMin - 1e-6:
                raise ValueError("The mounting seats require a plate that intersects the beam. "
                                 "This height combination needs separate supports; turn off Baseplate.")
    plate, _ = machined_baseplate.add(
        layout, position=(0, 0, top), thickness=thickness, margin=margin
    )
    try:
        layout.recompute()
    except ValueError as error:
        raise ValueError(f"Cannot machine baseplate: {error}. Check plate thickness and part presets.") from error
    return plate


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
