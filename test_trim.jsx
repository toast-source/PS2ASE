#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

try {
    var doc = app.documents.add(500, 500, 72, 'TrimTest', NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    var layer = doc.artLayers.add();
    
    // Draw a 10x10 square at (100, 100)
    var sel = [[100,100], [110,100], [110,110], [100,110]];
    doc.selection.select(sel);
    doc.selection.fill(app.foregroundColor);
    doc.selection.deselect();
    
    var wBefore = doc.width.as('px');
    try {
        doc.trim(TrimType.TRANSPARENT);
    } catch(e) {
        $.writeln('Trim Error: ' + e);
        var f = new File('C:/Users/SOUTHPAW GAMES/Desktop/AI TS/trim_test.txt');
        f.open('w'); f.write('Trim Error: ' + e); f.close();
    }
    
    var wAfter = doc.width.as('px');
    
    var logMsg = 'Before: ' + wBefore + ' | After: ' + wAfter;
    var logFile = new File('C:/Users/SOUTHPAW GAMES/Desktop/AI TS/trim_test.txt');
    logFile.open('w');
    logFile.write(logMsg);
    logFile.close();
    
    doc.close(SaveOptions.DONOTSAVECHANGES);

} catch(e) {
    var f = new File('C:/Users/SOUTHPAW GAMES/Desktop/AI TS/trim_test.txt');
    f.open('w'); f.write('ERR=' + e); f.close();
}
