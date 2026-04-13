local spr = Sprite(100, 100)
app.activeSprite = spr

-- Create Layer 1 (Red)
local l1 = spr.layers[1]
l1.name = "Layer_Red"
local img1 = Image(10, 10, spr.colorMode)
img1:clear()
for y=0, 9 do for x=0, 9 do img1:drawPixel(x, y, app.pixelColor.rgba(255,0,0,255)) end end
spr.cels[1].image = img1
spr.cels[1].position = Point(10, 10)

-- Create Layer 2 (Green)
local l2 = spr:newLayer()
l2.name = "Layer_Green"
l2.opacity = 127
local img2 = Image(20, 20, spr.colorMode)
img2:clear()
for y=0, 19 do for x=0, 19 do img2:drawPixel(x, y, app.pixelColor.rgba(0,255,0,255)) end end
spr:newCel(l2, 1, img2, Point(40, 40))

-- Create Layer 3 (Blue)
local l3 = spr:newLayer()
l3.name = "Layer_Blue"
l3.opacity = 255
local img3 = Image(15, 15, spr.colorMode)
img3:clear()
for y=0, 14 do for x=0, 14 do img3:drawPixel(x, y, app.pixelColor.rgba(0,0,255,255)) end end
spr:newCel(l3, 1, img3, Point(70, 10))

-- Select all 3 layers
app.range.layers = {l1, l2, l3}

-- Mock UI functions for batch mode
local originalAlert = app.alert
app.alert = function(msg) print("ALERT: " .. tostring(msg)) end
app.statusBar = { text = "" }

-- Execute Aseprite Copy Script
dofile("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/scripts/aseprite_copy.lua")

-- Save a log
local logFile = io.open("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/test_roundtrip_log.txt", "w")
logFile:write("Step 1: Aseprite Export Complete. StatusBar: " .. tostring(app.statusBar.text) .. "\n")
logFile:close()
