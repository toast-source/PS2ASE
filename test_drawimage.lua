local spr = Sprite(50, 50)
app.activeSprite = spr
app.activeColor = Color{ r=255, g=0, b=0, a=255 }

-- 캔버스 상의 (10, 10) 위치에 1x1 픽셀을 찍음
app.useTool{
    tool="pencil",
    color=app.activeColor,
    points={ Point(10, 10) }
}

local cel = spr.cels[1]
local bounds = cel.bounds
local img = cel.image

local logFile = io.open("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/test_drawimage_result.txt", "w")

logFile:write("Bounds: x=" .. bounds.x .. ", y=" .. bounds.y .. ", w=" .. bounds.width .. ", h=" .. bounds.height .. "\n")

-- 테스트 1: drawImage(img, 0, 0)
local testImg1 = Image(bounds.width, bounds.height, spr.colorMode)
testImg1:clear()
testImg1:drawImage(img, 0, 0)
local px1 = testImg1:getPixel(0, 0)

-- 테스트 2: drawImage(img, -bounds.x, -bounds.y)
local testImg2 = Image(bounds.width, bounds.height, spr.colorMode)
testImg2:clear()
testImg2:drawImage(img, -bounds.x, -bounds.y)
local px2 = testImg2:getPixel(0, 0)

logFile:write("Test 1 (0, 0) Pixel Value: " .. tostring(px1) .. "\n")
logFile:write("Test 2 (-x, -y) Pixel Value: " .. tostring(px2) .. "\n")

logFile:close()
