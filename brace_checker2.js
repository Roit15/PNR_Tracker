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
  if (open === 1 && line.includes('function') || line.includes('{')) {
      // Just to see where we might be stuck
  }
}

// Let's print the lines with indentation based on brace count
let current = 0;
for (let i = 0; i < lines.length; i++) {
  const line = lines[i].trim();
  if (!line) continue;
  let opens = (line.match(/\{/g) || []).length;
  let closes = (line.match(/\}/g) || []).length;
  
  if (closes > opens) current -= (closes - opens);
  console.log(`${i+1}: [${current}] ${line}`);
  if (opens > closes) current += (opens - closes);
}
