// scripts/photoshop_paste.jsx
// Ase-PS Bridge Pro - Paste Action (Photoshop)

#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

function main() {
    if (app.documents.length === 0) {
        alert("붙여넣기할 활성 문서가 없습니다. 새 문서를 열고 실행해주세요.");
        return;
    }
    
    var mainDoc = app.activeDocument;

    // 1. 클립보드 페이로드 읽기 (VBScript Fallback 사용)
    var payloadStr = getClipboardText();
    if (!payloadStr || payloadStr === "") {
        alert("클립보드가 비어있습니다. Aseprite에서 복사를 먼저 실행해주세요.");
        return;
    }

    var payload;
    try {
        payload = parseJSON(payloadStr);
    } catch(e) {
        alert("브릿지 데이터가 클립보드에 없습니다.\n일반 텍스트이거나 파싱할 수 없습니다.");
        return;
    }

    if (!payload || payload.signature !== "ase_ps_bridge_payload") {
        alert("유효한 Ase-PS Bridge 데이터가 아닙니다.");
        return;
    }

    var jobPath = payload.job_path;
    if (!jobPath) {
        alert("Payload에 job_path가 누락되었습니다.");
        return;
    }

    // 2. 메타데이터 로드
    var metaFile = new File(jobPath + "/metadata.json");
    if (!metaFile.exists) {
        alert("임시 전송 데이터가 삭제되었거나 만료되었습니다.\n(" + jobPath + ")");
        return;
    }

    metaFile.encoding = "UTF-8";
    metaFile.open("r");
    var metaContent = metaFile.read();
    metaFile.close();

    var metadata;
    try {
        metadata = parseJSON(metaContent);
    } catch(e) {
        alert("metadata.json 파싱 실패: " + e);
        return;
    }

    if (!metadata.layers || metadata.layers.length === 0) {
        alert("붙여넣을 레이어 데이터가 없습니다.");
        return;
    }

    // 3. 정렬 모드 (Alignment Policy) 확인
    var alignMode = "center"; // 기본값
    if (payload.settings && payload.settings.align_mode) {
        alignMode = payload.settings.align_mode;
    }

    // Bounding Box 계산 (콘텐츠 덩어리 정중앙 정렬용)
    var minX = null, minY = null, maxX = null, maxY = null;
    
    for (var i = 0; i < metadata.layers.length; i++) {
        var l = metadata.layers[i];
        var currentX = l.x;
        var currentY = l.y;
        var currentRight = l.x + l.width;
        var currentBottom = l.y + l.height;

        if (minX === null || currentX < minX) minX = currentX;
        if (minY === null || currentY < minY) minY = currentY;
        if (maxX === null || currentRight > maxX) maxX = currentRight;
        if (maxY === null || currentBottom > maxY) maxY = currentBottom;
    }

    // 콘텐츠 전체 크기
    var contentWidth = maxX - minX;
    var contentHeight = maxY - minY;

    // Aseprite 캔버스 중심에서 콘텐츠를 맞추기 위한 로컬 오프셋
    var aseCanvasW = metadata.canvas_size.w;
    var aseCanvasH = metadata.canvas_size.h;
    var offsetX = Math.floor((aseCanvasW - contentWidth) / 2) - minX;
    var offsetY = Math.floor((aseCanvasH - contentHeight) / 2) - minY;

    // 포토샵 캔버스와 Aseprite 캔버스의 크기 차이 보정 (포토샵 정중앙 안착)
    var psCanvasW = mainDoc.width.as("px");
    var psCanvasH = mainDoc.height.as("px");
    var psCenterX = Math.floor((psCanvasW - aseCanvasW) / 2);
    var psCenterY = Math.floor((psCanvasH - aseCanvasH) / 2);

    // 4. 레이어 조립 (Aseprite에서 온 순서 그대로 Bottom -> Top 삽입 유지)
    var importedCount = 0;

    for (var j = 0; j < metadata.layers.length; j++) {
        var lData = metadata.layers[j];
        var pngFile = new File(jobPath + "/" + lData.file);
        
        if (!pngFile.exists) {
            continue; // 누락된 파일 무시
        }

        // Open -> Duplicate 방식 (크기 왜곡 방지 및 정확한 1:1 픽셀 매핑)
        var pngDoc = app.open(pngFile);
        var pngLayer = pngDoc.activeLayer;
        
        // ElementPlacement.PLACEATBEGINNING 은 현재 레이어 스택의 맨 위로 올림
        // Aseprite 데이터는 0번 인덱스가 Bottom이므로 순차적으로 올리면 올바르게 위로 쌓임
        pngLayer.duplicate(mainDoc, ElementPlacement.PLACEATBEGINNING);
        pngDoc.close(SaveOptions.DONOTSAVECHANGES);
        
        app.activeDocument = mainDoc;
        var importedLayer = mainDoc.activeLayer; // 방금 복제되어 최상단에 올라온 레이어
        
        // 메타데이터 적용
        importedLayer.name = lData.name;
        // 브릿지 표준(0~100)을 포토샵 Opacity(0~100)에 그대로 적용
        importedLayer.opacity = lData.opacity; 
        importedLayer.visible = lData.visible;
        
        // Translate 이동 (Duplicate된 초기 위치가 0,0 임을 보장하므로 절대좌표처럼 사용 가능)
        var targetX, targetY;
        if (alignMode === "absolute") {
            // 원본 좌표를 그대로 유지
            targetX = lData.x;
            targetY = lData.y;
        } else {
            // 중앙 정렬 보정
            targetX = lData.x + offsetX + psCenterX;
            targetY = lData.y + offsetY + psCenterY;
        }
        
        importedLayer.translate(targetX, targetY);
        importedCount++;
    }

    if (importedCount > 0) {
        // UI 모니터와 별개로 스크립트 내부 피드백 (단독 실행 시를 위해)
        // alert(importedCount + "개 레이어 붙여넣기 완료"); 
    } else {
        alert("레이어를 불러오지 못했습니다. PNG 파일이 누락되었을 수 있습니다.");
    }
}

// ==========================================
// Helper Functions
// ==========================================

function getClipboardText() {
    // Photoshop ExtendScript에는 OS 클립보드를 읽는 API가 없으므로,
    // VBScript를 생성하여 임시 파일로 덤프한 뒤 읽어오는 꼼수 사용
    var tempFolder = new Folder("~/Desktop/AI TS/temp");
    if (!tempFolder.exists) tempFolder.create();
    
    var vbsFile = new File(tempFolder + "/ps_get_clip.vbs");
    var txtFile = new File(tempFolder + "/ps_clip_out.txt");
    
    // HTMLFile COM 객체를 이용해 텍스트 클립보드 탈취
    var vbsCode = 
        "On Error Resume Next\n" +
        "Set objHTML = CreateObject(\"htmlfile\")\n" +
        "text = objHTML.ParentWindow.ClipboardData.GetData(\"text\")\n" +
        "If IsNull(text) Then text = \"\"\n" +
        "Set objFSO = CreateObject(\"Scripting.FileSystemObject\")\n" +
        "Set objFile = objFSO.CreateTextFile(\"" + txtFile.fsName + "\", True, True)\n" + // True for Unicode
        "objFile.Write text\n" +
        "objFile.Close\n";
        
    vbsFile.open("w");
    vbsFile.write(vbsCode);
    vbsFile.close();
    
    vbsFile.execute();
    
    // VBScript가 실행되고 파일을 쓸 때까지 약간 대기
    $.sleep(300);
    
    var content = "";
    if (txtFile.exists) {
        txtFile.encoding = "UTF-16"; // CreateTextFile(..., True) saves as Unicode(UTF-16LE)
        txtFile.open("r");
        content = txtFile.read();
        txtFile.close();
        txtFile.remove();
    }
    vbsFile.remove();
    
    return content;
}

function parseJSON(str) {
    // Photoshop ExtendScript (ES3) 에는 내장 JSON 객체가 없으므로 eval을 통한 파싱
    // 보안 이슈가 있으나, 브릿지 내부 생성 데이터이므로 신뢰함
    try {
        var obj = eval("(" + str + ")");
        return obj;
    } catch(e) {
        throw new Error("JSON 파싱 실패");
    }
}

main();