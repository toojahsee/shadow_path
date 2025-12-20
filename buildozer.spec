[app]
title = Shadow Path
package.name = shadowpath
package.domain = org.shadowpath
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav
version = 1.0
requirements = python3,pygame,paho-mqtt
orientation = portrait
fullscreen = 1
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
