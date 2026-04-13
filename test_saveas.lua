local spr = app.activeSprite
if not spr then return end
local cel = spr.cels[1]
if not cel then return end
local img = cel.image
img:saveAs(`"C:\\Users\\SOUTHPAW GAMES\\Desktop\\AI TS\\temp_test_saveas.png`")
