const fs = require('fs');
const code = fs.readFileSync('rendered_script.js', 'utf8');
let open = 0;
let lines = code.split('\n');
for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  for (let c of line) {
    if (c === '{') open++;
    if (c === '}') open--;
  }
  if (open < 0) {
    console.log(`Too many closing braces at line ${i+1}`);
  }
}
console.log(`Final open count: ${open}`);
if (open > 0) {
    console.log("There is an unclosed brace!");
}
