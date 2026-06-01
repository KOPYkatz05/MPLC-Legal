{pkgs}: {
  deps = [
    pkgs.xorg.xauth
    pkgs.xorg.xorgserver
    pkgs.xcb-util-cursor
    pkgs.xorg.xcbutilrenderutil
    pkgs.xorg.xcbutilkeysyms
    pkgs.xorg.xcbutilimage
    pkgs.xorg.xcbutilwm
    pkgs.xorg.xcbutil
    pkgs.dbus
    pkgs.glib
    pkgs.zstd
    pkgs.xorg.libxkbfile
    pkgs.freetype
    pkgs.fontconfig
    pkgs.libGL
    pkgs.xorg.libXrandr
    pkgs.xorg.libXi
    pkgs.xorg.libXrender
    pkgs.xorg.libXext
    pkgs.xorg.libX11
    pkgs.xorg.libxcb
    pkgs.libxkbcommon
  ];
}
