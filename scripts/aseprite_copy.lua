-- scripts/aseprite_copy.lua
-- Ase-PS Bridge Pro - Copy Action (Aseprite to Bridge)

local function encodeJson(obj)
    -- Aseprite 내장 json.encode 지원 시 사용
    if type(json) == "table" and json.encode then
        return json.encode(obj)
    end
    
    -- Fallback: 매우 단순화된 수동 JSON 직렬화 (단일 뎁스 테이블용)
    local function escapeStr(s)
        return '"' .. tostring(s):gsub('"', '\\"') .. '"'
    end
    
    local parts = {}
    table.insert(parts, "{")
    
    local firstKey = true
    for k, v in pairs(obj) do
        if not firstKey then table.insert(parts, ",") end
        firstKey = false
        
        table.insert(parts, escapeStr(k) .. ":")
        
        if type(v) == "table" then
            if #v > 0 or next(v) == nil then
                -- Array
                table.insert(parts, "[")
                for i, item in ipairs(v) do
                    if i > 1 then table.insert(parts, ",") end
                    if type(item) == "table" then
                        table.insert(parts, encodeJson(item)) -- 재귀
                    else
                        table.insert(parts, encodeJson(item)) -- 이 코드는 객체 배열 처리용으로 작성됨
                    end
                end
                table.insert(parts, "]")
            else
                -- Dict (canvas_size 등)
                table.insert(parts, "{")
                local firstSub = true
                for subK, subV in pairs(v) do
                    if not firstSub then table.insert(parts, ",") end
                    firstSub = false
                    table.insert(parts, escapeStr(subK) .. ":" .. tostring(subV))
                end
                table.insert(parts, "}")
            end
        elseif type(v) == "string" then
            table.insert(parts, escapeStr(v))
        elseif type(v) == "boolean" then
            table.insert(parts, v and "true" or "false")
        else
            table.insert(parts, tostring(v))
        end
    end
    table.insert(parts, "}")
    return table.concat(parts)
end

local spr = app.activeSprite
if not spr then
    return app.alert("복사할 활성 문서가 없습니다.")
end

-- 1. 선택된 순수 그리기 레이어(isGroup/isReference 아님) 수집 (Bottom -> Top 순서 유지)
local selLayers = {}
local hasSelection = false

if app.range and app.range.layers then
    for _, l in ipairs(app.range.layers) do
        hasSelection = true
        if not l.isGroup and not l.isReference then
            -- Aseprite의 app.range.layers는 선택 순서일 수 있으므로, 
            -- 안전하게 전체 레이어를 순회하며 선택된 것만 담아 고정된 순서(Bottom->Top)를 보장.
            -- 아래 로직으로 지연 처리.
        end
    end
end

if hasSelection then
    for _, l in ipairs(spr.layers) do
        local isSelected = false
        for _, selL in ipairs(app.range.layers) do
            if l == selL then isSelected = true break end
        end
        if isSelected and not l.isGroup and not l.isReference then
            table.insert(selLayers, l)
        end
    end
else
    -- 단일 선택
    if app.activeLayer and not app.activeLayer.isGroup and not app.activeLayer.isReference then
        table.insert(selLayers, app.activeLayer)
    else
        return app.alert("복사할 픽셀 레이어를 선택해주세요 (그룹/레퍼런스 제외).")
    end
end

if #selLayers == 0 then
    return app.alert("선택된 영역에 유효한 픽셀 레이어가 없습니다.")
end

local frame = app.activeFrame or 1

-- 2. Job 폴더 준비 (OS 의존성 해결을 위해 powershell 사용 또는 단순 os.execute)
local timestamp = os.date("%Y%m%d_%H%M%S")
local jobDirName = "bridge_job_" .. timestamp .. "_" .. math.random(1000, 9999)
-- Windows 환경 가정
local baseTempPath = "C:/Users/SOUTHPAW GAMES/Desktop/AI TS/temp"
local jobPath = baseTempPath .. "/" .. jobDirName
local layersPath = jobPath .. "/layers"

-- 폴더 생성 (명령어 이스케이프 처리)
os.execute('mkdir "' .. jobPath:gsub("/", "\\") .. '"')
os.execute('mkdir "' .. layersPath:gsub("/", "\\") .. '"')

-- 3. 메타데이터 구성
local metadata = {
    version = "1.0",
    job_id = jobDirName,
    source_app = "aseprite",
    target_app = "photoshop",
    timestamp = timestamp,
    document_name = spr.filename:match("[^\\]+$") or "Untitled",
    canvas_size = { w = spr.width, h = spr.height },
    layers = {},
    layer_count = 0
}

local extractedCount = 0

-- 4. 레이어 추출 (수동 크롭 로직)
for i = 1, #selLayers do
    local layer = selLayers[i]
    local cel = layer:cel(frame.frameNumber)
    
    -- 빈 레이어(cel이 없거나 픽셀이 없는 경우)는 스킵하여 Bounding Box 왜곡 방지
    if cel and cel.image and not cel.image:isEmpty() then
        local bounds = cel.bounds
        
        -- 핵심: cel.image는 이미 캔버스 상의 자기 위치(bounds.x, bounds.y)와 무관하게 
        -- 내부적으로 0,0을 시작점으로 하는 크롭된 픽셀 덩어리임.
        -- 따라서 bounds 크기와 똑같은 새 이미지를 만들고, 0,0 위치에 그대로 옮겨 그리면 완벽한 1:1 크롭이 됨.
        local croppedImg = Image(bounds.width, bounds.height, spr.colorMode)
        croppedImg:clear()
        croppedImg:drawImage(cel.image, 0, 0)
        
        local fileName = "layer_" .. extractedCount .. ".png"
        local fullPngPath = layersPath .. "/" .. fileName
        
        croppedImg:saveAs(fullPngPath)
        
        table.insert(metadata.layers, {
            index = extractedCount,
            name = layer.name,
            x = bounds.x,
            y = bounds.y,
            width = bounds.width,
            height = bounds.height,
            -- Aseprite 불투명도(0~255)를 Bridge 표준(0~100 백분율)으로 정규화
            opacity = math.floor((layer.opacity / 255) * 100),
            visible = layer.isVisible,
            blendMode = "BlendMode.NORMAL",
            file = "layers/" .. fileName
        })
        
        extractedCount = extractedCount + 1
    end
end

if extractedCount == 0 then
    -- 추출된 레이어가 없으면 빈 폴더 삭제 후 종료
    os.execute('rmdir /S /Q "' .. jobPath:gsub("/", "\\") .. '"')
    return app.alert("선택된 레이어에 픽셀 데이터가 없어 복사하지 않았습니다.")
end

metadata.layer_count = extractedCount

-- 5. metadata.json 저장
local metaFile = io.open(jobPath .. "/metadata.json", "w")
if metaFile then
    metaFile:write(encodeJson(metadata))
    metaFile:close()
end

-- 6. Python Daemon용 trigger_copy.json 생성
local payload = {
    signature = "ase_ps_bridge_payload",
    version = "1.0",
    job_id = jobDirName,
    source_app = "aseprite",
    target_app = "photoshop",
    job_path = jobPath,
    summary = {
        layer_count = extractedCount,
        document_name = metadata.document_name
    },
    timestamp = timestamp
}

local triggerFile = io.open(jobPath .. "/trigger_copy.json", "w")
if triggerFile then
    triggerFile:write(encodeJson(payload))
    triggerFile:close()
end

-- UX 피드백 (app.statusBar 사용, 팝업으로 작업 흐름 끊지 않음)
if app.statusBar then
    app.statusBar.text = extractedCount .. "개 레이어가 브릿지 클립보드에 복사되었습니다."
else
    print(extractedCount .. "개 레이어 복사 완료")
end
