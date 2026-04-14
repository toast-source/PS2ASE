// scripts/photoshop_paste.jsx
// Ase-PS Bridge Pro - Paste Action (Photoshop)
// 지원: Layer/Group 계층(Tree) 구조 완벽 전송 및 100% 파일 시스템 IPC

var JOB_PATH = "REPLACE_ME_JOB_PATH";
var ALIGN_MODE = "REPLACE_ME_ALIGN_MODE";

#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

// 디버그 로깅용 유틸리티
function writeDebugLog(jobPath, msg) {
    try {
        var logFile = new File(jobPath + "/debug_ps_paste.log");
        logFile.encoding = "UTF-8";
        logFile.open("a");
        var d = new Date();
        var timeStr = d.getHours() + ":" + d.getMinutes() + ":" + d.getSeconds() + "." + d.getMilliseconds();
        logFile.writeln("[" + timeStr + "] " + msg);
        logFile.close();
    } catch(e) {}
}

function writeStatusError(errorMsg) {
    try {
        var errFile = new File(JOB_PATH + "/status_error.txt");
        errFile.encoding = "UTF-8";
        errFile.open("w");
        errFile.write(errorMsg);
        errFile.close();
    } catch(e) {}
}

function parseJSON(str) {
    try { return eval("(" + str + ")"); } 
    catch(e) { throw new Error("JSON 파싱 실패"); }
}

function main() {
    if (app.documents.length === 0) {
        writeStatusError("붙여넣기할 활성 문서가 없습니다. 새 문서를 열고 실행해주세요.");
        return;
    }
    
    var mainDoc = app.activeDocument;
    var jobPath = JOB_PATH;
    
    if (jobPath.indexOf("REPLACE_ME") !== -1) {
        writeStatusError("오류: 동적 래퍼 변수가 주입되지 않았습니다.");
        return;
    }

    var metaFile = new File(jobPath + "/metadata.json");
    if (!metaFile.exists) {
        writeStatusError("임시 전송 데이터(metadata.json)가 없습니다.");
        return;
    }

    var initLog = new File(jobPath + "/debug_ps_paste.log");
    if (initLog.exists) initLog.remove();
    writeDebugLog(jobPath, "=== Photoshop Paste Debug Log Started ===");

    metaFile.encoding = "UTF-8";
    metaFile.open("r");
    var metaContent = metaFile.read();
    metaFile.close();
    
    var metadata;
    try {
        metadata = parseJSON(metaContent);
    } catch(e) {
        writeStatusError("metadata.json 파싱 실패: " + e);
        return;
    }

    var elements = metadata.elements || metadata.layers;
    if (!elements || elements.length === 0) {
        writeStatusError("붙여넣을 레이어 데이터가 없습니다.");
        return;
    }
    
    writeDebugLog(jobPath, "Total elements to process: " + elements.length);

    var alignMode = ALIGN_MODE;
    writeDebugLog(jobPath, "Alignment Mode: " + alignMode);

    var minX = null, minY = null, maxX = null, maxY = null;
    
    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        if (el.type === "group") continue;
        
        var currentX = el.x || 0;
        var currentY = el.y || 0;
        var currentRight = currentX + (el.width || 0);
        var currentBottom = currentY + (el.height || 0);

        if (minX === null || currentX < minX) minX = currentX;
        if (minY === null || currentY < minY) minY = currentY;
        if (maxX === null || currentRight > maxX) maxX = currentRight;
        if (maxY === null || currentBottom > maxY) maxY = currentBottom;
    }

    var offsetX = 0, offsetY = 0, psCenterX = 0, psCenterY = 0;
    
    if (minX !== null && alignMode !== "absolute") {
        var contentWidth = maxX - minX;
        var contentHeight = maxY - minY;
        var aseCanvasW = metadata.canvas_size ? metadata.canvas_size.w : contentWidth;
        var aseCanvasH = metadata.canvas_size ? metadata.canvas_size.h : contentHeight;
        
        offsetX = Math.floor((aseCanvasW - contentWidth) / 2) - minX;
        offsetY = Math.floor((aseCanvasH - contentHeight) / 2) - minY;
        
        psCenterX = Math.floor((mainDoc.width.as("px") - aseCanvasW) / 2);
        psCenterY = Math.floor((mainDoc.height.as("px") - aseCanvasH) / 2);
        
        writeDebugLog(jobPath, "Calculated Offsets - Content Size: " + contentWidth + "x" + contentHeight);
    }

    var treeMap = {};
    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        var pId = el.parent_id || "root";
        if (!treeMap[pId]) treeMap[pId] = [];
        treeMap[pId].push(el);
    }

    for (var pId in treeMap) {
        treeMap[pId].sort(function(a, b) {
            var idxA = a.index !== undefined ? a.index : 0;
            var idxB = b.index !== undefined ? b.index : 0;
            return idxA - idxB;
        });
    }

    var importedCount = 0;

    function buildHierarchy(parentId, targetParentObj, depthString) {
        var children = treeMap[parentId];
        if (!children) return;

        for (var i = 0; i < children.length; i++) {
            var el = children[i];
            var newObj = null;

            if (el.type === "group") {
                newObj = targetParentObj.layerSets.add();
                newObj.name = el.name;
                newObj.opacity = el.opacity !== undefined ? el.opacity : 100;
                newObj.visible = el.visible !== undefined ? el.visible : true;
                
                buildHierarchy(el.id, newObj, depthString + "   ");
            } else {
                var pngFile = new File(jobPath + "/" + el.file);
                if (!pngFile.exists) continue;

                var pngDoc = app.open(pngFile);
                var pngLayer = pngDoc.activeLayer;
                
                pngLayer.duplicate(mainDoc, ElementPlacement.PLACEATBEGINNING);
                pngDoc.close(SaveOptions.DONOTSAVECHANGES);
                
                app.activeDocument = mainDoc;
                newObj = mainDoc.activeLayer;
                
                newObj.name = el.name || "Layer";
                newObj.opacity = el.opacity !== undefined ? el.opacity : 100;
                newObj.visible = el.visible !== undefined ? el.visible : true;
                
                var targetX = (el.x || 0) + offsetX + psCenterX;
                var targetY = (el.y || 0) + offsetY + psCenterY;
                
                if (alignMode === "absolute") {
                    targetX = (el.x || 0);
                    targetY = (el.y || 0);
                }
                
                newObj.translate(targetX, targetY);
                
                if (targetParentObj !== mainDoc) {
                    newObj.move(targetParentObj, ElementPlacement.INSIDE);
                }
                importedCount++;
            }
        }
    }

    writeDebugLog(jobPath, "--- Starting Hierarchy Build (root) ---");
    buildHierarchy("root", mainDoc, "");
    
    writeDebugLog(jobPath, "=== Photoshop Paste Completed. Total Imported: " + importedCount + " ===");

    // 성공 상태 파일 기록
    var timestamp = getFormattedDate();
    var doneData = {
        "job_id": jobPath,
        "status": "success",
        "layer_count": importedCount,
        "timestamp": timestamp
    };
    
    var doneFile = new File(JOB_PATH + "/status_done.json");
    doneFile.encoding = "UTF-8";
    doneFile.open("w");
    doneFile.write(JSONStringify(doneData));
    doneFile.close();
}

function getFormattedDate() {
    var d = new Date();
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear().toString() + pad(d.getMonth() + 1) + pad(d.getDate()) + "_" + 
           pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds());
}

function JSONStringify(obj) {
    if (obj === null) return "null";
    if (typeof obj === "string") return '"' + obj.replace(/"/g, '\\"') + '"';
    if (typeof obj === "number" || typeof obj === "boolean") return obj.toString();
    if (obj instanceof Array) {
        var arr = [];
        for (var i = 0; i < obj.length; i++) arr.push(JSONStringify(obj[i]));
        return "[" + arr.join(",") + "]";
    }
    if (typeof obj === "object") {
        var props = [];
        for (var key in obj) {
            if (obj.hasOwnProperty(key)) {
                props.push('"' + key + '":' + JSONStringify(obj[key]));
            }
        }
        return "{" + props.join(",") + "}";
    }
    return '""';
}

try {
    main();
} catch(e) {
    writeStatusError("포토샵 스크립트 전역 에러:\n" + e.toString());
}
