#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

try {
    var mainDoc = app.documents.add(200, 200, 72, 'OrderTest', NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    
    // 1. 최상단 폴더 생성
    var rootGroup = mainDoc.layerSets.add();
    rootGroup.name = 'RootGroup';

    // 2. 폴더 밖에서 레이어 3개 생성 (순차적 생성 시 기본적으로 Top에 쌓임)
    var l1 = mainDoc.artLayers.add(); l1.name = 'Layer_A';
    var l2 = mainDoc.artLayers.add(); l2.name = 'Layer_B';
    var l3 = mainDoc.artLayers.add(); l3.name = 'Layer_C';

    // 3. A -> B -> C 순서로 폴더 내부로 이동 (INSIDE 옵션 사용)
    l1.move(rootGroup, ElementPlacement.INSIDE); // A 넣기
    l2.move(rootGroup, ElementPlacement.INSIDE); // B 넣기
    l3.move(rootGroup, ElementPlacement.INSIDE); // C 넣기

    // 4. 폴더 안의 최종 레이어 순서 기록
    var logStr = 'INSIDE Move Order:\n';
    for (var i = 0; i < rootGroup.layers.length; i++) {
        logStr += '[' + i + '] ' + rootGroup.layers[i].name + '\n';
    }

    // 5. 파일에 결과 기록
    var logFile = new File('~/Desktop/AI TS/test_move_order.txt');
    logFile.open('w');
    logFile.write(logStr);
    logFile.close();
    
    mainDoc.close(SaveOptions.DONOTSAVECHANGES);

} catch(e) {
    var errFile = new File('~/Desktop/AI TS/test_move_order.txt');
    errFile.open('w');
    errFile.write('ERR=' + e);
    errFile.close();
}
