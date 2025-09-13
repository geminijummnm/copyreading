import json
import re
import os
from collections import defaultdict
from urllib.parse import urlparse

def get_base_domain(url):
    """从URL中提取主域名，用于没有明确名称的情况"""
    try:
        parsed_url = urlparse(url)
        # 提取域名部分
        domain = parsed_url.netloc
        if domain:
            return domain
        else:
            # 处理没有 scheme 的 URL
            parts = url.strip('/').split('/')
            if len(parts) >= 2:
                return parts[1]
            return parts[0]
    except Exception as e:
        print(f"提取域名时发生错误: {e}")
        return ""

def get_next_id():
    """从pm.json文件中获取下一个可用的分组ID"""
    pm_file_path = 'pm.json'
    print(f"正在读取文件：{pm_file_path}")
    if not os.path.exists(pm_file_path):
        print("错误：未找到 pm.json 文件。请确保文件存在。")
        return None
    
    try:
        with open(pm_file_path, 'r', encoding='utf-8') as f:
            pm_data = json.load(f)
            if 'groups' in pm_data and isinstance(pm_data['groups'], list) and pm_data['groups']:
                numeric_groups = [item for item in pm_data['groups'] if isinstance(item, int)]
                if numeric_groups:
                    return max(numeric_groups) + 1
                else:
                    print("警告：pm.json 的 'groups' 列表为空或不包含有效数字，将从 ID 0 开始。")
                    return 0
            else:
                print("警告：pm.json 文件中 'groups' 键不存在或格式不正确，将从 ID 0 开始。")
                return 0
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"读取或解析 pm.json 时发生错误：{e}")
        return None

def process_txt_files():
    """
    处理当前目录下所有txt文件，提取分组信息，生成.json文件并更新pm.json
    """
    next_id = get_next_id()
    if next_id is None:
        return

    txt_files = [f for f in os.listdir('.') if f.endswith('.txt')]
    if not txt_files:
        print("当前目录下没有找到任何 .txt 文件。")
        return
        
    print(f"已找到 {len(txt_files)} 个 .txt 文件。")
    all_new_entries = []
    
    # 编译多种正则表达式以应对不同格式
    # Pattern 1: 带表情符号的格式
    pattern1 = re.compile(r'📋\s*机场名称:\s*(.+)\n🔗\s*订阅链接:\s*(.+)', re.MULTILINE)
    # Pattern 2: 不带表情符号的格式
    pattern2 = re.compile(r'机场名称:\s*(.+)\n订阅链接:\s*(.+)', re.MULTILINE)
    # Pattern 3: 仅URL
    pattern3 = re.compile(r'https?://[^\s]+', re.MULTILINE)

    for file_name in txt_files:
        print(f"\n--- 正在处理文件：{file_name} ---")
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"读取文件 {file_name} 时发生错误：{e}")
            continue

        entries_found = False
        
        # 尝试使用第一种模式
        matches = pattern1.findall(content)
        if matches:
            for name, url in matches:
                all_new_entries.append({'name': name.strip(), 'url': url.strip()})
            entries_found = True
        
        # 如果第一种模式失败，尝试第二种模式
        if not entries_found:
            matches = pattern2.findall(content)
            if matches:
                for name, url in matches:
                    all_new_entries.append({'name': name.strip(), 'url': url.strip()})
                entries_found = True

        # 如果前两种模式都失败，尝试仅提取URL
        if not entries_found:
            print(f"文件中未找到“机场名称”和“订阅链接”标签，将尝试提取所有URL。")
            urls_only = pattern3.findall(content)
            if urls_only:
                for url in urls_only:
                    name = get_base_domain(url.strip())
                    if name:
                        all_new_entries.append({'name': name, 'url': url.strip()})
        
        if not matches and not urls_only:
            print("未在此文件中找到任何有效的分组信息。")


    if not all_new_entries:
        print("\n所有文件中未找到任何新的分组信息。")
        return

    name_counts = defaultdict(int)
    processed_entries = set()
    final_entries = []

    for entry in all_new_entries:
        name = entry['name']
        url = entry['url']
        
        # 检查是否为完全重复的条目
        if (name, url) in processed_entries:
            print(f"跳过完全重复条目：名称='{name}', 订阅链接='{url}'")
            continue
        processed_entries.add((name, url))
        
        base_name = name
        current_name = name
        
        # 检查名称是否重复，并进行编号
        if base_name in name_counts:
             current_name = f"{base_name} ({name_counts[base_name]})"
        
        name_counts[base_name] += 1
        final_entries.append({'name': current_name, 'url': url})

    new_ids = []
    print(f"\n即将创建 {len(final_entries)} 个新的分组文件。")
    
    for entry in final_entries:
        file_name = f"{next_id}.json"
        
        config_data = {
            "archive": False,
            "front_proxy_id": -1,
            "id": next_id,
            "info": "",
            "landing_proxy_id": -1,
            "lastup": 0,
            "manually_column_width": False,
            "name": entry['name'],
            "skip_auto_update": False,
            "url": entry['url']
        }

        try:
            with open(file_name, 'w', encoding='utf-8') as outfile:
                json.dump(config_data, outfile, ensure_ascii=False, indent=4)
            print(f"已创建文件：{file_name}，名称：{entry['name']}")
            new_ids.append(next_id)
        except Exception as e:
            print(f"写入文件 {file_name} 时发生错误：{e}")
            
        next_id += 1

    # 更新 pm.json 文件
    pm_file_path = 'pm.json'
    if new_ids:
        try:
            with open(pm_file_path, 'r+', encoding='utf-8') as pm_file:
                pm_data = json.load(pm_file)
                pm_data['groups'].extend(new_ids)
                pm_file.seek(0)
                json.dump(pm_data, pm_file, ensure_ascii=False, indent=4)
                pm_file.truncate()
            print(f"\npm.json 文件已更新，添加了 {len(new_ids)} 个新的分组 ID。")
            print("所有任务已完成！")
        except Exception as e:
            print(f"\n更新 pm.json 时发生错误：{e}")
    else:
        print("\n没有新的分组需要添加，pm.json 未更新。")
        
if __name__ == '__main__':
    try:
        process_txt_files()
    except Exception as e:
        print(f"\n脚本运行过程中出现未捕获的严重错误：{e}")
