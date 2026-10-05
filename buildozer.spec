[app]
title = پارکینگ من
package.name = parkingman
package.domain = org.parking
source.dir = .
source.include_exts = py,ttf
version = 0.1
requirements = python3,kivy==2.3.0,pyjnius,android,arabic-reshaper,python-bidi==0.4.2,six
orientation = portrait
fullscreen = 0
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.permissions = INTERNET,BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_SCAN,ACCESS_FINE_LOCATION

[buildozer]
log_level = 2
warn_on_root = 0