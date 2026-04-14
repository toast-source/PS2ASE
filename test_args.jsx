#target photoshop
var args = [];
try { args = arguments; } catch(e) {}
var msg = 'Args length: ' + args.length;
for (var i=0; i<args.length; i++) { msg += '\nArg['+i+']: ' + args[i]; }
var f = new File('~/Desktop/AI TS/test_args.txt');
f.open('w'); f.write(msg); f.close();
