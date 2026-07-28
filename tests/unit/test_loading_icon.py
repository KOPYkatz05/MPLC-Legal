from ui.foundation import create_loading_icon


def test_loading_icon_factory_animates_and_hides_cleanly(qapp):
    _ = qapp
    icon = create_loading_icon(size=16)

    assert icon.width() == 16
    assert icon.isHidden()

    icon.start()
    assert icon._timer.isActive()
    assert not icon.isHidden()

    icon.stop()
    assert not icon._timer.isActive()
    assert icon.isHidden()
