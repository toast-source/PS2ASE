// scripts/photoshop_copy.jsx
// Ase-PS Bridge Pro - Copy Action (Photoshop)

#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

function main() {
    if (app.documents.length === 0) return;
    var originalDoc = app.activeDocument;

    // 1. 선택된 레이어들을 새로운 임시 문서로 복제 (다중 선택을 완벽하게 가져오는 가장 안전한 방법)
    try {
        var desc = new ActionDescriptor();
        var ref = new ActionReference();
        ref.putClass(charIDToTypeID("Dcmn"));
        desc.putReference(charIDToTypeID("null"), ref);
        desc.putString(charIDToTypeID("Nm  "), "TempBridgeDoc");
        var ref2 = new ActionReference();
        ref2.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
        desc.putReference(charIDToTypeID("Usng"), ref2);
        executeAction(charIDToTypeID("Mk  "), desc, DialogModes.NO);
    } catch (e) {
        alert("선택된 레이어가 없습니다. 전송할 레이어들을 선택한 후 다시 실행해주세요.");
        return;
    }

    // 복제된 임시 문서가 활성 문서가 됨
    var tempDoc = app.activeDocument;
    var exportedLayers = getFlatLayers(tempDoc); // 그룹 무시, 일반 레이어만 추출

    // 사전 필터링: 빈 레이어 미리 제거하여 불필요한 I/O 작업 원천 차단
    var validLayers = [];
    for (var i = 0; i < exportedLayers.length; i++) {
        var l = exportedLayers[i];
        if (l.bounds[2].as("px") - l.bounds[0].as("px") > 0 && l.bounds[3].as("px") - l.bounds[1].as("px") > 0) {
            validLayers.push(l);
        }
    }

    if (validLayers.length === 0) {
        alert("추출 가능한 픽셀 레이어가 없습니다 (모두 빈 레이어거나 그룹입니다). 전송할 이미지가 있는 레이어를 선택해주세요.");
        tempDoc.close(SaveOptions.DONOTSAVECHANGES);
        app.activeDocument = originalDoc;
        return;
    }

    // 2. Job 폴더 및 경로 준비
    var timestamp = getFormattedDate();
    var jobDirName = "bridge_job_" + timestamp + "_" + Math.floor(Math.random() * 10000);
    var baseTempPath = new Folder("~/Desktop/AI TS/temp");
    if (!baseTempPath.exists) baseTempPath.create();
    
    var jobFolder = new Folder(baseTempPath + "/" + jobDirName);
    jobFolder.create();
    var layersFolder = new Folder(jobFolder + "/layers");
    layersFolder.create();

    // 3. 메타데이터 구성 시작
    var metadata = {
        "version": "1.0",
        "job_id": jobDirName,
        "source_app": "photoshop",
        "target_app": "aseprite",
        "timestamp": timestamp,
        "document_name": originalDoc.name,
        "canvas_size": { "w": originalDoc.width.as("px"), "h": originalDoc.height.as("px") },
        "layers": []
    };

    // 4. 레이어 추출 (Photoshop DOM 배열은 Top -> Bottom 순서임. 이를 역순(Bottom -> Top)으로 저장하여 Aseprite와 맞춤)
    var extractedCount = 0;
    for (var i = validLayers.length - 1; i >= 0; i--) {
        var layer = validLayers[i];

        var x = parseInt(layer.bounds[0].as("px"));
        var y = parseInt(layer.bounds[1].as("px"));
        var w = parseInt(layer.bounds[2].as("px")) - x;
        var h = parseInt(layer.bounds[3].as("px")) - y;

        var fileName = "layer_" + extractedCount + ".png";
        var pngPath = layersFolder + "/" + fileName;

        // 투명도 유지하여 PNG 내보내기
        exportLayerAsPNG(tempDoc, layer, pngPath);

        metadata.layers.push({
            "index": extractedCount,
            "name": layer.name,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "opacity": Math.round(layer.opacity),
            "visible": layer.visible,
            "blendMode": layer.blendMode.toString(),
            "file": "layers/" + fileName
        });
        
        extractedCount++;
    }

    // 작업 끝났으므로 임시 복제 문서 닫기
    tempDoc.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument = originalDoc;

    metadata.layer_count = metadata.layers.length;
    saveJSON(jobFolder + "/metadata.json", metadata);

    // 5. Python Daemon에게 클립보드 주입 지시
    var payload = {
        "signature": "ase_ps_bridge_payload",
        "version": "1.0",
        "job_id": jobDirName,
        "source_app": "photoshop",
        "target_app": "aseprite",
        "job_path": jobFolder.fsName.replace(/\\/g, "/"),
        "summary": {
            "layer_count": metadata.layer_count,
            "document_name": originalDoc.name
        },
        "timestamp": timestamp
    };
    saveJSON(jobFolder + "/trigger_copy.json", payload);

    // UX 피드백 (Copy 완료)
    alert(metadata.layer_count + "개 레이어가 브릿지 클립보드에 복사되었습니다.");
}

// ==========================================
// Helper Functions
// ==========================================

// 폴더(그룹) 구조를 무시하고 순수 ArtLayer들만 배열로 수집 (Top -> Bottom)
function getFlatLayers(docOrGroup) {
    var flat = [];
    for (var i = 0; i < docOrGroup.layers.length; i++) {
        var l = docOrGroup.layers[i];
        if (l.typename === "LayerSet") {
            // 그룹 안에 있는 레이어도 재귀적으로 모두 빼냄
            flat = flat.concat(getFlatLayers(l));
        } else if (l.typename === "ArtLayer") {
            flat.push(l);
        }
    }
    return flat;
}

function exportLayerAsPNG(doc, layer, fullPath) {
    var exportDoc = app.documents.add(doc.width, doc.height, doc.resolution, "ExportTemp", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    app.activeDocument = doc;
    
    layer.duplicate(exportDoc, ElementPlacement.PLACEATBEGINNING);
    app.activeDocument = exportDoc;
    
    try { exportDoc.trim(TrimType.TRANSPARENT); } catch(e) {}
    
    var saveFile = new File(fullPath);
    var pngOptions = new PNGSaveOptions();
    pngOptions.compression = 0;
    pngOptions.interlaced = false;
    
    exportDoc.saveAs(saveFile, pngOptions, true, Extension.LOWERCASE);
    exportDoc.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument = doc;
}

function getFormattedDate() {
    var d = new Date();
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear().toString() + pad(d.getMonth() + 1) + pad(d.getDate()) + "_" + 
           pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds());
}

function saveJSON(path, obj) {
    var file = new File(path);
    file.encoding = "UTF-8";
    file.open("w");
    file.write(customStringify(obj));
    file.close();
}

function customStringify(obj) {
    if (obj === null) return "null";
    if (typeof obj === "string") return '"' + obj.replace(/"/g, '\\"') + '"';
    if (typeof obj === "number" || typeof obj === "boolean") return obj.toString();
    if (obj instanceof Array) {
        var arr = [];
        for (var i = 0; i < obj.length; i++) arr.push(customStringify(obj[i]));
        return "[" + arr.join(",") + "]";
    }
    if (typeof obj === "object") {
        var props = [];
        for (var key in obj) {
            if (obj.hasOwnProperty(key)) {
                props.push('"' + key + '":' + customStringify(obj[key]));
            }
        }
        return "{" + props.join(",") + "}";
    }
    return '""';
}

main();