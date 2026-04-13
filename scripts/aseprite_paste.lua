-- scripts/aseprite_paste.lua
-- Ase-PS Bridge Pro - Paste Action (Aseprite)

local function decodeJson(str)
    -- Aseprite 내장 json.decode 또는 대체 파서 처리
    if type(json) == "table" and json.decode then
        return json.decode(str)
    end
    -- Fallback: 극단적으로 단순화된 패턴 매칭 (에러 대비)
    local obj = {}
    obj.signature = str:match('"signature"%s*:%s*"([^"]+)"')
    obj.job_path = str:match('"job_path"%s*:%s*"([^"]+)"')
    return obj
end

local function showMessage(msg)
    app.alert({ title="Bridge Paste", text=msg, buttons={"OK"} })
end

-- 1. 활성 스프라이트 확인 (선택 사항: 없으면 새로 만들 수도 있지만 현재 문서에 붙여넣는 UX)
local spr = app.activeSprite
if not spr then
    showMessage("붙여넣기할 활성 문서가 없습니다. 새 문서를 열고 실행해주세요.")
    return
end

-- 2. OS 클립보드 검사
local clipboardText = ""
if app.clipboard and app.clipboard.text then
    clipboardText = app.clipboard.text
end

if not clipboardText or clipboardText == "" then
    -- Fallback: powershell을 이용하여 OS 클립보드 직접 읽기
    local handle = io.popen("powershell.exe -NoProfile -Command \"Get-Clipboard\"")
    if handle then
        clipboardText = handle:read("*a")
        handle:close()
    end
end

if not clipboardText or clipboardText:match("^%s*$") then
    showMessage("클립보드가 비어있습니다. Photoshop에서 복사를 먼저 실행해주세요.")
    return
end

-- 3. Payload 검증
local payload = decodeJson(clipboardText)
if not payload or payload.signature ~= "ase_ps_bridge_payload" then
    showMessage("브릿지 데이터가 클립보드에 없습니다.\n일반 텍스트이거나 Photoshop에서 Bridge Copy를 실행하지 않았습니다.")
    return
end

local jobPath = payload.job_path
if not jobPath then
    showMessage("Payload에 job_path가 누락되었습니다.")
    return
end

-- 4. 메타데이터 로드
local metaFile = io.open(jobPath .. "/metadata.json", "r")
if not metaFile then
    showMessage("임시 전송 데이터가 삭제되었거나 만료되었습니다.\n(" .. jobPath .. ")")
    return
end
local metaContent = metaFile:read("*all")
metaFile:close()

-- 포토샵 캔버스 사이즈 추출 (더 이상 전체 캔버스 중앙 정렬 기준이 아님, 참고용)
local ps_w = tonumber(metaContent:match('"canvas_size".-"w"%s*:%s*(%d+)')) or spr.width
local ps_h = tonumber(metaContent:match('"canvas_size".-"h"%s*:%s*(%d+)')) or spr.height

-- 5. 레이어 데이터 파싱 및 Bounding Box 계산
local layersData = {}
local minX, minY, maxX, maxY

-- Aseprite 내장 JSON 모듈을 우선 사용하여 특수문자/따옴표 파싱 에러 원천 차단
local parsedMeta = nil
if type(json) == "table" and json.decode then
    parsedMeta = json.decode(metaContent)
end

if parsedMeta and parsedMeta.layers then
    for _, lData in ipairs(parsedMeta.layers) do
        local lx = tonumber(lData.x) or 0
        local ly = tonumber(lData.y) or 0
        local fullImagePath = jobPath .. "/" .. lData.file
        table.insert(layersData, {
            name = lData.name or "Layer",
            x = lx,
            y = ly,
            op = tonumber(lData.opacity) or 100,
            file = lData.file,
            fullImagePath = fullImagePath
        })
    end
else
    -- Fallback: JSON 모듈이 없는 구버전 환경을 위한 정규식
    for name, x, y, op, vis, file in metaContent:gmatch('"name"%s*:%s*"([^"]*)",%s*"x"%s*:%s*(%-?%d+),%s*"y"%s*:%s*(%-?%d+).-"opacity"%s*:%s*(%d+),%s*"visible"%s*:%s*(%w+).-"file"%s*:%s*"([^"]+)"') do
        local lx = tonumber(x) or 0
        local ly = tonumber(y) or 0
        local fullImagePath = jobPath .. "/" .. file
        
        table.insert(layersData, {
            name = name,
            x = lx,
            y = ly,
            op = tonumber(op) or 100,
            file = file,
            fullImagePath = fullImagePath
        })
    end
end

if #layersData == 0 then
    showMessage("붙여넣을 레이어 데이터가 없습니다.")
    return
end

-- 이미지 크기를 읽어 전체 콘텐츠의 최소/최대 Bounding Box 구하기
for i = 1, #layersData do
    local lData = layersData[i]
    local imgFile = io.open(lData.fullImagePath, "rb")
    if imgFile then
        imgFile:close()
        local importedImage = Image{ fromFile = lData.fullImagePath }
        if importedImage then
            lData.img = importedImage -- 이미지 객체 캐싱
            local lw, lh = importedImage.width, importedImage.height
            if not minX or lData.x < minX then minX = lData.x end
            if not minY or lData.y < minY then minY = lData.y end
            if not maxX or (lData.x + lw) > maxX then maxX = lData.x + lw end
            if not maxY or (lData.y + lh) > maxY then maxY = lData.y + lh end
        end
    end
end

-- 전체 픽셀 콘텐츠 덩어리의 크기
local contentWidth = (maxX or 0) - (minX or 0)
local contentHeight = (maxY or 0) - (minY or 0)

-- Aseprite 캔버스 정중앙에 콘텐츠를 맞추기 위한 보정값 (Offset)
local offsetX = math.floor((spr.width - contentWidth) / 2) - (minX or 0)
local offsetY = math.floor((spr.height - contentHeight) / 2) - (minY or 0)

-- 6. 레이어 재구성 (Transaction으로 묶어 한번에 실행 및 취소 지원)
local importedCount = 0
local frame = app.activeFrame or 1

-- Aseprite의 그룹 레이어(isGroup)를 제외한 순수 그리기 레이어만 추출
local flatLayers = {}
for _, l in ipairs(spr.layers) do
    if not l.isGroup then
        table.insert(flatLayers, l)
    end
end

-- 덮어씌울 타겟 레이어들을 미리 수집
local targetLayers = {}
local selLayers = {}
local selCount = 0

if app.range and app.range.layers then
    for _, l in ipairs(app.range.layers) do
        if not l.isGroup then 
            selLayers[l] = true 
            selCount = selCount + 1
        end
    end
end

if selCount == #layersData then
    -- 1. 사용자가 레이어 갯수를 딱 맞춰서 다중 선택한 경우
    for _, l in ipairs(flatLayers) do
        if selLayers[l] then table.insert(targetLayers, l) end
    end
else
    -- 2. 단일 선택이거나 갯수가 안 맞는 경우, 기존 레이어를 '최대한' 재사용
    local activeIdx = 1
    if app.activeLayer and not app.activeLayer.isGroup then
        for i, l in ipairs(flatLayers) do
            if l == app.activeLayer then
                activeIdx = i
                break
            end
        end
    end
    
    local startIdx = activeIdx
    
    -- 선택한 레이어 위쪽으로 공간이 부족하다면, 시작점을 아래로 끌어내림
    -- (목표: 기존 레이어 개수가 충분하다면 절대 새 레이어를 만들지 않음)
    if startIdx + #layersData - 1 > #flatLayers then
        startIdx = #flatLayers - #layersData + 1
        if startIdx < 1 then startIdx = 1 end
    end
    
    for i = 1, #layersData do
        local l = flatLayers[startIdx + i - 1]
        if l then
            table.insert(targetLayers, l)
        else
            break -- 여전히 부족하면 여기서 break (이후에 새 레이어 생성)
        end
    end
end

app.transaction(function()
    for i = 1, #layersData do
        local lData = layersData[i]
        local targetLayer = targetLayers[i]
        
        -- 핵심 Fallback: 모든 기존 레이어를 끌어다 썼는데도 모자랄 때만 새 레이어 추가
        if not targetLayer then
            targetLayer = spr:newLayer()
            -- 포토샵의 레이어 이름을 복사하지 않고 기본 이름 유지
            table.insert(targetLayers, targetLayer)
        end
        
        if lData.img then
            targetLayer.opacity = math.floor(lData.op * 2.55)
            
            local finalX = lData.x + offsetX
            local finalY = lData.y + offsetY
            
            local existingCel = targetLayer:cel(frame.frameNumber or 1)
            if existingCel then
                spr:deleteCel(existingCel)
            end
            
            spr:newCel(targetLayer, frame, lData.img, Point(finalX, finalY))
            importedCount = importedCount + 1
        end
    end
end)

app.refresh()

-- 6. UX 피드백
if importedCount > 0 then
    -- Aseprite 하단 상태 표시줄에 표시 (최신 Aseprite UI)
    if app.statusBar then
        app.statusBar.text = importedCount .. "개 레이어 붙여넣기 완료"
    else
        print(importedCount .. "개 레이어 붙여넣기 완료")
    end
else
    showMessage("레이어를 생성하지 못했습니다. 전송 데이터(PNG)가 손상되었을 수 있습니다.")
end