const fs = require('fs');
let html = fs.readFileSync('templates/index.html', 'utf8');

const regex = /<script>([\s\S]*?)<\/script>/gi;
let match = regex.exec(html);
let code = match[1];

// Replace Jinja stuff with valid JS placeholders
code = code.replace(/\{\{\s*url_for[^}]*\}\}/g, '"dummy_url"');
code = code.replace(/\{\{\s*bookings\|length\s*\}\}/g, '0');
code = code.replace(/\{%\s*if[^%]*%\}/g, '');
code = code.replace(/\{%\s*endif\s*%\}/g, '');

fs.writeFileSync('temp_clean.js', code);

try {
  const { execSync } = require('child_process');
  execSync('node -c temp_clean.js', { stdio: 'pipe' });
  console.log("No syntax errors found by node -c!");
} catch (e) {
  console.log("Error output:");
  console.log(e.stderr.toString());
}
