import os
import json

CACHE_FILE = "data/cache/export_cache.json"


def show_stats(cache):
    print(f"  目前快取：{len(cache)} 筆")
    classified = sum(1 for v in cache.values() if v.get("types") and v["types"] != "其他")
    unknown_addr = sum(1 for v in cache.values() if not v.get("address") or v["address"] == "未知地址")
    print(f"  已分類（非「其他」）：{classified} 筆")
    print(f"  地址未知：{unknown_addr} 筆")


def load_cache():
    if not os.path.exists(CACHE_FILE):
        print("快取檔案不存在，無需清除。")
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def clear_all(cache):
    count = len(cache)
    cache.clear()
    save_cache(cache)
    print(f"[完成] 已清除全部 {count} 筆快取。")


def clear_unknown_address(cache):
    bad = [k for k, v in cache.items()
           if not v.get("address") or v["address"] == "未知地址"]
    for k in bad:
        del cache[k]
    save_cache(cache)
    print(f"[完成] 已清除 {len(bad)} 筆地址未知的快取。")


def clear_near_coords(cache):
    try:
        lat_str = input("  輸入緯度（例如 24.825）：").strip()
        lng_str = input("  輸入經度（例如 120.981）：").strip()
        threshold_str = input("  清除半徑（公里，直接 Enter 預設 1.0）：").strip()
        lat = float(lat_str)
        lng = float(lng_str)
        threshold = float(threshold_str) if threshold_str else 1.0
        deg = threshold / 111.0  # 1 度約 111 公里
    except ValueError:
        print("[錯誤] 輸入格式不正確。")
        return

    bad = [k for k, v in cache.items()
           if v.get("lat") and v.get("lng")
           and abs(v["lat"] - lat) < deg
           and abs(v["lng"] - lng) < deg]
    for k in bad:
        del cache[k]
    save_cache(cache)
    print(f"[完成] 已清除座標在 ({lat}, {lng}) {threshold} 公里內的 {len(bad)} 筆快取。")


def main():
    print("====== 快取管理工具 ======")
    cache = load_cache()
    if cache is None:
        return

    show_stats(cache)
    print()
    print("請選擇操作：")
    print("  1. 清除全部快取（下次執行重新分析所有店家）")
    print("  2. 只清除地址未知的快取")
    print("  3. 清除特定座標附近的快取（修正定位錯誤）")
    print("  0. 取消離開")

    choice = input("\n請輸入選項：").strip()

    if choice == "1":
        confirm = input(f"確定要清除全部 {len(cache)} 筆？(y/N)：").strip().lower()
        if confirm == "y":
            clear_all(cache)
        else:
            print("已取消。")
    elif choice == "2":
        clear_unknown_address(cache)
    elif choice == "3":
        clear_near_coords(cache)
    elif choice == "0":
        print("已取消。")
    else:
        print("無效選項。")


if __name__ == "__main__":
    main()
