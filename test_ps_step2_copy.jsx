#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

try {
    var mainDoc = app.activeDocument;
    
    // Select all layers (except background)
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
    desc.putReference(charIDToTypeID("null"), ref);
    executeAction(stringIDToTypeID("selectAllLayers"), desc, DialogModes.NO);
    
    // Mock alert
    var oldAlert = alert;
    alert = function(msg) { $.writeln("ALERT: " + msg); };
    
    var copyFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/scripts/photoshop_copy.jsx");
    $.evalFile(copyFile);
    
    alert = oldAlert;
} catch(e) {
    var logFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/test_ps_log2.txt");
    logFile.encoding = "UTF-8";
    logFile.open("w");
    logFile.write("ERROR: " + e);
    logFile.close();
}
