# utils.py - 工具模块

import re
import jieba.posseg as pseg

PUNCTUATION = ['。', '！', '？', '!', '?', '\n', '；', ';', '：', ':', '，', ',']

def clean_text(text):
    """清除表情符号和多余特殊字符"""
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s' + "".join(PUNCTUATION) + r']', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_entities(text):
    """从文本中自动提取可能的实体"""
    entities = set()
    words = pseg.cut(text)
    
    for word, flag in words:
        if flag in ['nr', 'ns', 'nt', 'nz', 'n']:
            if len(word) >= 1:
                entities.add(word)
        
        if any(word.endswith(suffix) for suffix in ['公司', '大学', '医院', '学校', '银行', '政府', '中心', '局', '部']):
            entities.add(word)
        
        if re.match(r'\d{11}', word):
            entities.add(word)
        if '@' in word and '.' in word:
            entities.add(word)
    
    return entities