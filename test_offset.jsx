#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

try {
    var mainDoc = app.documents.add(500, 500, 72, 'MainTest', NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    var tempFile = new File('~/Desktop/AI TS/temp_test_offset.png');
    
    // Create 50x50 PNG
    var tempDoc = app.documents.add(50, 50, 72, 'TempTest', NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    tempDoc.selection.selectAll();
    tempDoc.selection.fill(app.foregroundColor);
    tempDoc.saveAs(tempFile, new PNGSaveOptions(), true, Extension.LOWERCASE);
    tempDoc.close(SaveOptions.DONOTSAVECHANGES);
    
    // Open and Duplicate
    var openedDoc = app.open(tempFile);
    openedDoc.activeLayer.duplicate(mainDoc, ElementPlacement.PLACEATBEGINNING);
    openedDoc.close(SaveOptions.DONOTSAVECHANGES);
    
    app.activeDocument = mainDoc;
    var duplicatedLayer = mainDoc.activeLayer;
    
    var x = duplicatedLayer.bounds[0].as('px');
    var y = duplicatedLayer.bounds[1].as('px');
    
    var logMsg = 'X_OFFSET=' + x + '|Y_OFFSET=' + y;
    
    var logFile = new File('~/Desktop/AI TS/test_offset_result.txt');
    logFile.open('w');
    logFile.write(logMsg);
    logFile.close();
    
    mainDoc.close(SaveOptions.DONOTSAVECHANGES);
    tempFile.remove();

} catch(e) {
    var errFile = new File('~/Desktop/AI TS/test_offset_result.txt');
    errFile.open('w');
    errFile.write('ERR=' + e);
    errFile.close();
}
