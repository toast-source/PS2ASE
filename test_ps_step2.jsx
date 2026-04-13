#target photoshop
app.preferences.rulerUnits = Units.PIXELS;

try {
    var mainDoc = app.documents.add(200, 200, 72, "RoundtripTest", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);

    // Mock alert to prevent blocking
    var oldAlert = alert;
    alert = function(msg) { $.writeln("ALERT: " + msg); };

    // Run Paste Script
    var pasteFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/scripts/photoshop_paste.jsx");
    $.evalFile(pasteFile);

    var logStr = "PS Import Results:\n";
    // Check imported layers (excluding background if any)
    for (var i = 0; i < mainDoc.layers.length; i++) {
        var l = mainDoc.layers[i];
        if (l.bounds[2].as("px") - l.bounds[0].as("px") <= 0) continue;
        var x = l.bounds[0].as("px");
        var y = l.bounds[1].as("px");
        var w = l.bounds[2].as("px") - x;
        var h = l.bounds[3].as("px") - y;
        logStr += "Name: " + l.name + ", X: " + x + ", Y: " + y + ", W: " + w + ", H: " + h + ", Opacity: " + Math.round(l.opacity) + "\n";
    }

    var logFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/test_ps_log.txt");
    logFile.encoding = "UTF-8";
    logFile.open("w");
    logFile.write(logStr);
    logFile.close();

    // Select layers for Copy Script (Actually photoshop_copy uses getFlatLayers on a duplicate doc, so it gets ALL layers)
    // Wait, photoshop_copy.jsx does: getFlatLayers(tempDoc). It copies the whole doc.
    var copyFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/scripts/photoshop_copy.jsx");
    $.evalFile(copyFile);

    // Restore alert
    alert = oldAlert;
    
    // Close doc
    mainDoc.close(SaveOptions.DONOTSAVECHANGES);

} catch(e) {
    var logFile = new File("C:/Users/SOUTHPAW GAMES/Desktop/AI TS/test_ps_log.txt");
    logFile.encoding = "UTF-8";
    logFile.open("w");
    logFile.write("ERROR: " + e);
    logFile.close();
}
