from bs4 import BeautifulSoup
import sys

def find_inputs(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
        
        inputs = soup.find_all('input')
        for inp in inputs:
            print(f"Input: name={inp.get('name')}, id={inp.get('id')}, type={inp.get('type')}, class={inp.get('class')}")
            
if __name__ == '__main__':
    find_inputs('debug_ai_form.html')
