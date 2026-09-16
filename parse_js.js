const fs = require('fs');
const html = fs.readFileSync('templates/index.html', 'utf8');

// extremely basic extraction of script tags
const regex = /<script>([\s\S]*?)<\/script>/gi;
let match;
while ((match = regex.exec(html)) !== null) {
  const code = match[1];
  try {
    // using new Function to check syntax
    new Function(code);
  } catch (e) {
    console.log("Syntax error in <script>:", e.message);
    
    // trying to isolate the error line by writing to a temp file and running it
    fs.writeFileSync('temp_script.js', code);
    const { execSync } = require('child_process');
    try {
      execSync('node -c temp_script.js', { stdio: 'pipe' });
    } catch(err) {
      console.log(err.stderr.toString());
    }
  }
}
