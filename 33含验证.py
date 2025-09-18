import json
import re
import os
from collections import defaultdict
from urllib.parse import urlparse
import sys
import requests
from requests.exceptions import RequestException, ConnectionError, Timeout
from concurrent.futures import ThreadPoolExecutor
import datetime
import socks
import yaml

# 检查 requests, PySocks 和 PyYAML 库是否已安装
try:
    import requests
    import socks
    import yaml
except ImportError:
    print("错误: 缺少必要的库。请先使用以下命令安装：")
    print("pip install \"requests[socks]\" PySocks pyyaml")
    sys.exit()

def get_base_domain(url):
    """从URL中提取主域名，用于没有明确名称的情况"""
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        if domain:
            return domain
        else:
            parts = url.strip('/').split('/')
            if len(parts) >= 2:
                return parts[1]
            return parts[0]
    except Exception as e:
        return ""

def get_next_id():
    """从pm.json文件中获取下一个可用的分组ID"""
    pm_file_path = 'pm.json'
    print(f"正在读取文件：{pm_file_path}")
    if not os.path.exists(pm_file_path):
        print("警告：未找到 pm.json 文件，将从 ID 0 开始。")
        return 0
    
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
        print(f"读取或解析 pm.json 时发生错误：{e}，将从 ID 0 开始。")
        return 0

def is_url_valid(entry, proxies_list):
    """验证单个 URL，并返回验证结果和失败原因"""
    url = entry['url']
    user_agents = {
        'chrome': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'clashmeta': 'Clash-Verge/1.3.1',
        'singbox': 'sing-box'
    }

    def try_request(current_proxies=None):
        for ua_name, ua_string in user_agents.items():
            headers = {'User-Agent': ua_string}
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            
            try:
                response = requests.head(url, timeout=15, allow_redirects=True, proxies=current_proxies, headers=headers)
                
                if 200 <= response.status_code < 400:
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 成功！")
                    return True, "成功"
                elif response.status_code in [403, 405, 429]:
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 成功 (状态码: {response.status_code}, 视为成功！)")
                    return True, f"状态码: {response.status_code}"
                else:
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 失败 (状态码: {response.status_code})。")
                    return False, f"状态码: {response.status_code}"
            except Timeout:
                print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 失败 (超时)。")
                return False, "超时"
            except ConnectionError as e:
                if '10054' in str(e):
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 成功 (网络连接错误: 10054, 视为成功！)")
                    return True, "网络连接错误: 10054"
                elif '10053' in str(e):
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 失败 (网络连接错误: 10053, 将尝试其他代理)。")
                    continue
                else:
                    print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 失败 (网络请求错误: {e})。")
                    return False, f"网络请求错误: {e}"
            except RequestException as e:
                print(f"-> 正在{'直接' if not current_proxies else '通过代理'}验证 URL: {url} ... UA:{ua_name} {current_time} 失败 (网络请求错误: {e})。")
                return False, f"网络请求错误: {e}"
        return False, "所有UA均失败"

    is_success, reason = try_request()
    if is_success:
        return True, entry
    
    if proxies_list:
        print("正在尝试使用代理...")
        for proxy_address in proxies_list:
            proxies = {
                "http": proxy_address,
                "https": proxy_address,
            }
            try:
                is_success, reason = try_request(proxies)
                if is_success:
                    return True, entry
            except (socks.SocksError, requests.exceptions.ProxyError) as e:
                print(f"警告: 代理 {proxy_address} 连接失败: {e}。将尝试下一个代理。")
                reason = f"代理连接失败: {e}"
                continue
            except RequestException as e:
                print(f"警告: 代理 {proxy_address} 验证失败: {e}。将尝试下一个代理。")
                reason = f"代理验证失败: {e}"
                continue
    
    print(f"所有尝试均失败。链接: {url}")
    return False, {'name': entry['name'], 'url': url, 'failedReason': reason}

def extract_subscriptions_from_files():
    """从多种文件中提取订阅链接，并进行去重"""
    all_new_entries = []
    
    txt_files = [f for f in os.listdir('.') if f.endswith('.txt')]
    json_files = [f for f in os.listdir('.') if f.endswith('.json') and f != 'pm.json']
    yaml_files = [f for f in os.listdir('.') if f.endswith('.yaml') or f.endswith('.yml')]

    # 从TXT文件中提取
    txt_count = 0
    pattern1 = re.compile(r'📋\s*机场名称:\s*(.+)\n🔗\s*订阅链接:\s*(.+)', re.MULTILINE)
    pattern2 = re.compile(r'机场名称:\s*(.+)\n订阅链接:\s*(.+)', re.MULTILINE)
    pattern3 = re.compile(r'https?://[^\s]+', re.MULTILINE)
    for file_name in txt_files:
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = pattern1.findall(content)
                if not matches:
                    matches = pattern2.findall(content)
                if matches:
                    for name, url in matches:
                        all_new_entries.append({'name': name.strip(), 'url': url.strip()})
                    txt_count += len(matches)
                else:
                    urls_only = pattern3.findall(content)
                    if urls_only:
                        for url in urls_only:
                            url = url.strip()
                            if url:
                                name = get_base_domain(url)
                                if name:
                                    all_new_entries.append({'name': name, 'url': url})
                        txt_count += len(urls_only)
        except Exception as e:
            print(f"读取文件 {file_name} 时发生错误：{e}")
    print(f"识别到 TXT 文件 {len(txt_files)} 个，获取订阅 {txt_count} 个。")

    # 从JSON文件中提取
    json_count = 0
    for file_name in json_files:
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'name' in data and 'url' in data:
                    all_new_entries.append({'name': data['name'].strip(), 'url': data['url'].strip()})
                    json_count += 1
        except Exception as e:
            pass
    print(f"识别到 JSON 文件 {len(json_files)} 个，获取订阅 {json_count} 个。")

    # 从YAML文件中提取
    yaml_count = 0
    for file_name in yaml_files:
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and 'proxies' in data:
                    for proxy in data['proxies']:
                        if isinstance(proxy, dict) and 'name' in proxy and 'url' in proxy:
                            all_new_entries.append({'name': proxy['name'].strip(), 'url': proxy['url'].strip()})
                            yaml_count += 1
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'url' in item:
                            name = item.get('name', get_base_domain(item['url']))
                            all_new_entries.append({'name': name.strip(), 'url': item['url'].strip()})
                            yaml_count += 1
        except Exception as e:
            print(f"读取文件 {file_name} 时发生错误：{e}")
    print(f"识别到 YAML 文件 {len(yaml_files)} 个，获取订阅 {yaml_count} 个。")
    
    return all_new_entries

def deduplicate_with_existing(entries, choice):
    """根据用户选择，进行第二步外部去重"""
    existing_urls = set()
    deduplicated_entries = []
    
    if choice == 'nekobox':
        json_files = [f for f in os.listdir('.') if f.endswith('.json') and f != 'pm.json']
        for file_name in json_files:
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'url' in data:
                        existing_urls.add(data['url'].strip())
            except Exception as e:
                print(f"读取现有 JSON 文件 {file_name} 时发生错误：{e}")
    
    elif choice == 'singbox':
        yaml_file_path = 'subscribes.yaml'
        if os.path.exists(yaml_file_path):
            try:
                with open(yaml_file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and 'proxies' in data:
                        proxies_list = data['proxies']
                    elif isinstance(data, list):
                        proxies_list = data
                    else:
                        proxies_list = []

                    for proxy in proxies_list:
                        if isinstance(proxy, dict) and 'url' in proxy:
                            existing_urls.add(proxy['url'].strip())
            except Exception as e:
                print(f"读取现有 YAML 文件 {yaml_file_path} 时发生错误：{e}")
    
    processed_new_entries = set()
    for entry in entries:
        if (entry['name'], entry['url']) in processed_new_entries:
            continue
        processed_new_entries.add((entry['name'], entry['url']))
        
        if entry['url'] not in existing_urls:
            deduplicated_entries.append(entry)
    
    return deduplicated_entries
    
def write_singbox_yaml(final_entries):
    """将成功的订阅写入 sing-box 配置文件"""
    yaml_file_path = 'subscribes.yaml'
    
    existing_proxies = []
    if os.path.exists(yaml_file_path):
        try:
            with open(yaml_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and 'proxies' in data:
                    existing_proxies = data['proxies']
                elif isinstance(data, list):
                    existing_proxies = data
        except Exception as e:
            print(f"警告：读取现有 {yaml_file_path} 文件时发生错误：{e}。将创建新文件。")
    
    new_proxies = []
    for entry in final_entries:
        new_proxies.append({'name': entry['name'], 'url': entry['url']})
    
    final_proxies = existing_proxies + new_proxies
    
    config_data = {'proxies': final_proxies}
    
    try:
        with open(yaml_file_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, allow_unicode=True, indent=2, sort_keys=False)
        print(f"Singbox 配置文件已成功更新。")
    except Exception as e:
        print(f"写入 Singbox 配置文件时发生错误：{e}")

def write_nekobox_json(final_entries):
    """将成功的订阅写入 nekobox 配置文件"""
    next_id = get_next_id()
    if next_id is None:
        return
        
    name_counts = defaultdict(int)
    new_ids = []
    for entry in final_entries:
        base_name = entry['name']
        current_name = base_name
        if name_counts[base_name] > 0:
             current_name = f"{base_name} ({name_counts[base_name]})"
        name_counts[base_name] += 1
        
        file_name = f"{next_id}.json"
        
        config_data = {
            "archive": False,
            "front_proxy_id": -1,
            "id": next_id,
            "info": "",
            "landing_proxy_id": -1,
            "lastup": 0,
            "manually_column_width": False,
            "name": current_name,
            "skip_auto_update": False,
            "url": entry['url']
        }

        try:
            with open(file_name, 'w', encoding='utf-8') as outfile:
                json.dump(config_data, outfile, ensure_ascii=False, indent=4)
            print(f"已创建文件：{file_name}，名称：{current_name}")
            new_ids.append(next_id)
        except Exception as e:
            print(f"写入文件 {file_name} 时发生错误：{e}")
            
        next_id += 1

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
        except Exception as e:
            print(f"\n更新 pm.json 时发生错误：{e}")


def main():
    while True:
        choice = input("请选择要生成的配置类型 (nekobox/singbox): ").strip().lower()
        if choice in ['nekobox', 'singbox']:
            break
        print("输入无效，请输入 'nekobox' 或 'singbox'。")

    all_new_entries = extract_subscriptions_from_files()

    if not all_new_entries:
        print("\n所有文件中未找到任何新的分组信息。")
        return
    
    unique_entries = deduplicate_with_existing(all_new_entries, choice)

    if not unique_entries:
        print("\n所有新订阅已存在于现有配置文件中，无需添加。")
        return

    while True:
        try:
            num_threads = int(input("请输入要使用的线程数 (建议2-16，或直接回车使用默认8): ").strip() or "8")
            if num_threads > 0:
                break
            else:
                print("线程数必须为正整数。")
        except ValueError:
            print("输入无效，请输入一个数字。")

    proxies_input = input("请输入代理地址，多个代理用英文逗号分隔 (例如: socks5://127.0.0.1:1080,http://192.168.1.1:8080，或直接回车跳过): ").strip()
    proxies_list = [p.strip() for p in proxies_input.split(',') if p.strip()]
    if proxies_list:
        print(f"已配置 {len(proxies_list)} 个代理，将仅在直接访问失败时使用。")

    print(f"去重后共 {len(unique_entries)} 条独立订阅链接，正在使用 {num_threads} 线程进行验证...")

    final_entries = []
    failed_entries = []
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = executor.map(lambda e: is_url_valid(e, proxies_list), unique_entries)
        
        for is_success, result_data in results:
            if is_success:
                final_entries.append(result_data)
            else:
                failed_entries.append(result_data)

    print(f"\n验证完成，共找到 {len(final_entries)} 个有效订阅链接，{len(failed_entries)} 个失败订阅链接。")

    # 写入 suc.jpg
    suc_entries_formatted = [{'name': entry['name'], 'url': entry['url']} for entry in final_entries]
    with open('suc.jpg', 'w', encoding='utf-8') as f:
        json.dump(suc_entries_formatted, f, ensure_ascii=False, indent=4)
    print("已生成 suc.jpg 文件。")

    # 写入 fa.jpg
    fa_entries_formatted = [{'name': entry['name'], 'url': entry['url']} for entry in failed_entries]
    with open('fa.jpg', 'w', encoding='utf-8') as f:
        json.dump(fa_entries_formatted, f, ensure_ascii=False, indent=4)
    print("已生成 fa.jpg 文件。")

    # 根据用户选择生成最终文件
    if choice == 'nekobox':
        write_nekobox_json(final_entries)
    elif choice == 'singbox':
        write_singbox_yaml(final_entries)

    print("\n所有任务已完成！")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n脚本运行过程中出现未捕获的严重错误：{e}")