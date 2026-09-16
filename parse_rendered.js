const fs = require('fs');
let html = fs.readFileSync('local_rendered.html', 'utf8');

const regex = /<script>([\s\S]*?)<\/script>/gi;
let match;
while ((match = regex.exec(html)) !== null) {
  const code = match[1];
  fs.writeFileSync('rendered_script.js', code);
  const { execSync } = require('child_process');
  try {
    execSync('node -c rendered_script.js', { stdio: 'pipe' });
    console.log("No syntax errors found by node -c!");
  } catch (e) {
    console.log("Error output:");
    console.log(e.stderr.toString());
  }
}
