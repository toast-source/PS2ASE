-- scripts/aseprite_paste.lua
-- Ase-PS Bridge Pro - Paste Action (Aseprite)
-- 지원: Layer/Group 계층(Tree) 구조 완벽 전송 및 평면(Flat) 레이어 덮어쓰기

local function decodeJson(str)
    if type(json) == "table" and json.decode then return json.decode(str) end
    local obj = {}
    obj.signature = str:match('"signature"%s*:%s*"([^"]+)"')
    obj.job_path = str:match('"job_path"%s*:%s*"([^"]+)"')
    return obj
end

local function showMessage(msg)
    app.alert({ title="Bridge Paste", text=msg, buttons={"OK"} })
end

local spr = app.activeSprite
if not spr then
    showMessage("붙여넣기할 활성 문서가 없습니다. 새 문서를 열고 실행해주세요.")
    return
end

local clipboardText = ""
if app.clipboard and app.clipboard.text then
    clipboardText = app.clipboard.text
end

if not clipboardText or clipboardText == "" then
    local handle = io.popen("powershell.exe -NoProfile -Command \"Get-Clipboard\"")
    if handle then
        clipboardText = handle:read("*a")
        handle:close()
    end
end

if not clipboardText or clipboardText:match("^%s*$") then
    showMessage("클립보드가 비어있습니다. 포토샵에서 복사를 먼저 실행해주세요.")
    return
end

local payload = decodeJson(clipboardText)
if not payload or payload.signature ~= "ase_ps_bridge_payload" then return end

local jobPath = payload.job_path
if not jobPath then return end

-- Debug Logger
local function writeLog(msg)
    local f = io.open(jobPath .. "/debug_ase_paste.log", "a")
    if f then
        f:write(msg .. "\n")
        f:close()
    end
end
os.remove(jobPath .. "/debug_ase_paste.log")
writeLog("=== Aseprite Paste Debug Log ===")
writeLog("Align Mode: " .. tostring(payload.settings and payload.settings.align_mode))

local metaFile = io.open(jobPath .. "/metadata.json", "r")
if not metaFile then
    showMessage("임시 전송 데이터가 삭제되었거나 만료되었습니다.")
    return
end
local metaContent = metaFile:read("*all")
metaFile:close()

local metadata = nil
if type(json) == "table" and json.decode then
    metadata = json.decode(metaContent)
end

if not metadata then
    showMessage("메타데이터 파싱 실패.")
    return
end

local elementsList = metadata.elements or metadata.layers
if not elementsList or #elementsList == 0 then
    showMessage("붙여넣을 데이터가 없습니다.")
    return
end

local alignMode = "center"
if payload.settings and payload.settings.align_mode then
    alignMode = payload.settings.align_mode
end

-- 1. [공통] 전략 분기점 판별: 그룹이 하나라도 있는지 확인
local hasGroup = false
for i = 1, #elementsList do
    if elementsList[i].type == "group" then
        hasGroup = true
        break
    end
end
writeLog("Has Group: " .. tostring(hasGroup))

-- 2. [공통] Bounding Box 기반 Offset 계산 (그룹 제외, 보이는 레이어 중심)
local minX, minY, maxX, maxY
-- 1차 시도: 눈이 켜져 있는(visible) 레이어만으로 Bounding Box 계산 (배경 등 숨긴 레이어 때문에 중심축이 어긋나는 현상 방지)
for i = 1, #elementsList do
    local el = elementsList[i]
    if el.type ~= "group" and el.visible ~= false then
        local cx = tonumber(el.x) or 0
        local cy = tonumber(el.y) or 0
        local cRight = cx + (tonumber(el.width) or 0)
        local cBottom = cy + (tonumber(el.height) or 0)

        if not minX or cx < minX then minX = cx end
        if not minY or cy < minY then minY = cy end
        if not maxX or cRight > maxX then maxX = cRight end
        if not maxY or cBottom > maxY then maxY = cBottom end
    end
end

-- 만약 모든 레이어가 숨김 처리되어 있다면 전체 레이어로 2차 계산
if minX == nil then
    for i = 1, #elementsList do
        local el = elementsList[i]
        if el.type ~= "group" then
            local cx = tonumber(el.x) or 0
            local cy = tonumber(el.y) or 0
            local cRight = cx + (tonumber(el.width) or 0)
            local cBottom = cy + (tonumber(el.height) or 0)

            if not minX or cx < minX then minX = cx end
            if not minY or cy < minY then minY = cy end
            if not maxX or cRight > maxX then maxX = cRight end
            if not maxY or cBottom > maxY then maxY = cBottom end
        end
    end
end

writeLog("Bounding Box - minX: " .. tostring(minX) .. ", minY: " .. tostring(minY) .. ", maxX: " .. tostring(maxX) .. ", maxY: " .. tostring(maxY))

local offsetX, offsetY = 0, 0
if minX ~= nil and alignMode ~= "absolute" then
    local contentWidth = maxX - minX
    local contentHeight = maxY - minY
    local psCanvasW = (metadata.canvas_size and metadata.canvas_size.w) or contentWidth
    local psCanvasH = (metadata.canvas_size and metadata.canvas_size.h) or contentHeight
    
    offsetX = math.floor((spr.width - contentWidth) / 2) - minX
    offsetY = math.floor((spr.height - contentHeight) / 2) - minY
    
    writeLog("Calculated - contentWidth: " .. contentWidth .. ", contentHeight: " .. contentHeight)
    writeLog("Offsets - offsetX: " .. offsetX .. ", offsetY: " .. offsetY)
end

local importedCount = 0
local frame = app.activeFrame or 1

app.transaction(function()

    if not hasGroup then
        -- ==========================================
        -- 분기 1: Legacy Flat Overwrite Mode
        -- 그룹이 없으면 기존 레이어를 덮어씌움
        -- ==========================================
        
        -- 순수 그리기 레이어만 추출 (그룹 내부에 있는 레이어도 모두 수집)
        local flatLayers = {}
        local function collectFlat(layersCollection)
            for _, l in ipairs(layersCollection) do
                if not l.isGroup then table.insert(flatLayers, l) end
                if l.isGroup then collectFlat(l.layers) end
            end
        end
        collectFlat(spr.layers)

        local targetLayers = {}
        
        -- 단일 선택 또는 미선택 (자동 공간 유추 - Active Layer 기준 아래로 덮어쓰기)
        local activeIdx = #flatLayers -- 선택이 없으면 캔버스의 가장 위쪽 레이어부터
        if app.activeLayer and not app.activeLayer.isGroup then
            for i, l in ipairs(flatLayers) do
                if l == app.activeLayer then
                    activeIdx = i
                    break
                end
            end
        end

        -- 포토샵에서 가져온 레이어 뭉치 중 '가장 위쪽(Top) 레이어'가 현재 Aseprite의 Active Layer에 안착하도록,
        -- 시작점(Bottom)을 Active Layer보다 아래쪽으로 계산하여 내려갑니다.
        local bottomIdx = activeIdx - #elementsList + 1

        -- 만약 아래쪽으로 덮어쓸 레이어가 모자라다면 (1번 레이어보다 밑으로 뚫고 내려갈 경우),
        -- 어쩔 수 없이 1번 레이어부터 위로 채워넣도록 방어합니다.
        if bottomIdx < 1 then 
            bottomIdx = 1 
        end

        for i = 1, #elementsList do
            local l = flatLayers[bottomIdx + i - 1]
            if l then table.insert(targetLayers, l) end
        end

        for i = 1, #elementsList do
            local el = elementsList[i]
            local targetLayer = targetLayers[i]
            
            if not targetLayer then
                targetLayer = spr:newLayer()
            end
            
            local fullImagePath = jobPath .. "/" .. el.file
            local imgFile = io.open(fullImagePath, "rb")
            if imgFile then
                imgFile:close()
                local img = Image{ fromFile = fullImagePath }
                if img then
                    targetLayer.opacity = math.floor((tonumber(el.opacity) or 100) * 2.55)
                    
                    local existingCel = targetLayer:cel(frame.frameNumber)
                    if existingCel then spr:deleteCel(existingCel) end
                    
                    local finalX = (tonumber(el.x) or 0) + offsetX
                    local finalY = (tonumber(el.y) or 0) + offsetY
                    if alignMode == "absolute" then
                        finalX = tonumber(el.x) or 0
                        finalY = tonumber(el.y) or 0
                    end
                    
                    spr:newCel(targetLayer, frame, img, Point(finalX, finalY))
                    importedCount = importedCount + 1
                end
            end
        end

    else
        -- ==========================================
        -- 분기 2: Hierarchy Reconstruct Mode
        -- 그룹이 있으면 안전하게 통째로 새 트리 생성
        -- ==========================================
        local treeMap = {}
        for i = 1, #elementsList do
            local el = elementsList[i]
            local pId = el.parent_id or "root"
            if not treeMap[pId] then treeMap[pId] = {} end
            table.insert(treeMap[pId], el)
        end

        for pId, children in pairs(treeMap) do
            table.sort(children, function(a, b)
                local idxA = tonumber(a.index) or 0
                local idxB = tonumber(b.index) or 0
                return idxA < idxB
            end)
        end

        local function buildHierarchy(parentId, targetParentObj)
            local children = treeMap[parentId]
            if not children then return end
            
            for i = 1, #children do
                local el = children[i]
                local newObj = nil
                
                if el.type == "group" then
                    newObj = spr:newGroup()
                    newObj.name = el.name
                    newObj.opacity = math.floor((tonumber(el.opacity) or 100) * 2.55)
                    if targetParentObj ~= spr then newObj.parent = targetParentObj end
                    buildHierarchy(el.id, newObj)
                else
                    local fullImagePath = jobPath .. "/" .. el.file
                    local imgFile = io.open(fullImagePath, "rb")
                    if imgFile then
                        imgFile:close()
                        local importedImage = Image{ fromFile = fullImagePath }
                        if importedImage then
                            newObj = spr:newLayer()
                            newObj.name = el.name or "Layer"
                            newObj.opacity = math.floor((tonumber(el.opacity) or 100) * 2.55)
                            if targetParentObj ~= spr then newObj.parent = targetParentObj end
                            
                            local finalX = (tonumber(el.x) or 0) + offsetX
                            local finalY = (tonumber(el.y) or 0) + offsetY
                            if alignMode == "absolute" then
                                finalX = tonumber(el.x) or 0
                                finalY = tonumber(el.y) or 0
                            end
                            
                            spr:newCel(newObj, frame, importedImage, Point(finalX, finalY))
                            importedCount = importedCount + 1
                        end
                    end
                end
            end
        end

        buildHierarchy("root", spr)
    end
end)

app.refresh()

if importedCount > 0 then
    if app.statusBar then
        app.statusBar.text = importedCount .. "개 항목 붙여넣기 완료"
    else
        print(importedCount .. "개 항목 붙여넣기 완료")
    end
else
    showMessage("레이어를 생성하지 못했습니다. 전송 데이터가 손상되었을 수 있습니다.")
end