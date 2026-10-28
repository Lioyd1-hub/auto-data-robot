#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto-data-robot 核心流程引擎
多系统数据搬运机器人：从多个业务系统导出的对账数据，
自动搬运进汇总表，结果回写并标记状态，支持异常兜底与无人值守。

用法：
    python robot_core.py --once        # 单次搬运（演示）
    python robot_core.py --schedule    # 进入调度模式（无人值守）
"""

import argparse
import csv
import datetime
import json
import os
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# 轻量配置（实际项目可用 config.yaml 覆盖）
# ---------------------------------------------------------------------------
CONFIG = {
    "source_systems": ["erp", "crm", "finance"],   # 三个源系统
    "summary_file": "summary.xlsx",                 # 汇总表
    "status_column": "搬运状态",                     # 回写状态列
    "wait_image_timeout": 10,                        # 页面加载等待超时（秒）
    "retry_times": 3,                               # 失败重试次数
    "maintenance_window": ("02:00", "04:00"),       # 维护时段窗口
    "log_dir": "logs",
    "screenshot_dir": "screenshots",
}


class DataRobot:
    """数据搬运机器人：读表 -> 录入 -> 回写 -> 归档 -> 兜底。"""

    def __init__(self, config=None):
        self.cfg = config or CONFIG
        self.error_log = []
        Path(self.cfg["log_dir"]).mkdir(exist_ok=True)
        Path(self.cfg["screenshot_dir"]).mkdir(exist_ok=True)

    # -- 日志与截图 -------------------------------------------------------
    def log(self, level, msg):
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}"
        print(line)
        with open(Path(self.cfg["log_dir"]) / "run.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def screenshot(self, order_id, reason):
        """失败时截图留证（真实 RPA 场景下调用界面截图，这里落盘占位）。"""
        fn = Path(self.cfg["screenshot_dir"]) / f"fail_{order_id}_{int(time.time())}.png"
        with open(fn, "w", encoding="utf-8") as f:
            f.write(f"截图占位：单号 {order_id} 失败原因 {reason}\n")
        return str(fn)

    # -- 核心：模拟从源系统读取待处理单号 --------------------------------
    def load_orders(self, system):
        """从源系统导出的 CSV 读取待处理单号（真实项目此处对接各系统导出文件）。"""
        rows = []
        for i in range(1, 8):  # 示例：每个系统 7 条
            rows.append({
                "单号": f"{system.upper()}-{20260000 + i}",
                "金额": round(1000 + i * 137.5, 2),
                "来源系统": system,
            })
        return rows

    # -- 界面元素定位 + 等待 + 重试（模拟慢页面） ------------------------
    def locate_and_fill(self, order, retry=0):
        """模拟界面元素定位与录入；加载慢则等待，超时重试。"""
        if retry < 2 and order["单号"].endswith(("3", "7")):
            # 模拟个别慢页面/元素定位失败，触发重试
            self.log("WARN", f"单号 {order['单号']} 页面加载慢，等待 {self.cfg['wait_image_timeout']}s 后重试")
            time.sleep(0.2)
            return self.locate_and_fill(order, retry + 1)
        # 定位成功，返回录入结果
        return {"单号": order["单号"], "金额": order["金额"], "来源系统": order["来源系统"]}

    # -- 主流程 -----------------------------------------------------------
    def run_once(self):
        """单次搬运：遍历源系统 -> 逐单搬运 -> 回写状态 -> 失败兜底。"""
        self.log("INFO", "===== 开始数据搬运 =====")
        summary = []
        for system in self.cfg["source_systems"]:
            orders = self.load_orders(system)
            for order in orders:
                try:
                    result = self.locate_and_fill(order)
                    result["搬运状态"] = "已完成"
                    summary.append(result)
                    self.log("INFO", f"单号 {order['单号']} 搬运成功")
                except Exception as e:  # 异常兜底：截图 + 错误日志，不中断整体
                    shot = self.screenshot(order["单号"], str(e))
                    self.error_log.append({"单号": order["单号"], "错误": str(e), "截图": shot})
                    self.log("ERROR", f"单号 {order['单号']} 失败：{e}（已截图 {shot}）")
        # 回写汇总 + 错误日志
        self.write_summary(summary)
        self.write_error_log()
        self.log("INFO", f"===== 搬运完成：成功 {len(summary)} 条，失败 {len(self.error_log)} 条 =====")
        return len(summary), len(self.error_log)

    def write_summary(self, rows):
        out = Path(self.cfg["summary_file"])
        with open(str(out).replace(".xlsx", ".csv"), "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["单号", "金额", "来源系统", "搬运状态"])
            writer.writeheader()
            writer.writerows(rows)
        self.log("INFO", f"汇总表已回写 {len(rows)} 条")

    def write_error_log(self):
        if not self.error_log:
            return
        fn = Path(self.cfg["log_dir"]) / "error_sample.log"
        with open(fn, "a", encoding="utf-8") as f:
            for e in self.error_log:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # -- 无人值守调度（维护时段等待） ------------------------------------
    def in_maintenance_window(self):
        start, end = self.cfg["maintenance_window"]
        now = datetime.datetime.now().strftime("%H:%M")
        return start <= now <= end

    def run_schedule(self):
        """无人值守：维护时段阻塞等待，其余时间按周期搬运。"""
        self.log("INFO", "进入无人值守调度模式（Ctrl+C 退出）")
        while True:
            if self.in_maintenance_window():
                self.log("INFO", f"处于维护时段 {self.cfg['maintenance_window']}，阻塞等待")
                time.sleep(60)
                continue
            self.run_once()
            time.sleep(3600)  # 每小时一轮


def main():
    parser = argparse.ArgumentParser(description="多系统数据搬运机器人")
    parser.add_argument("--once", action="store_true", help="单次搬运")
    parser.add_argument("--schedule", action="store_true", help="无人值守调度")
    args = parser.parse_args()

    robot = DataRobot()
    if args.schedule:
        robot.run_schedule()
    else:
        robot.run_once()


if __name__ == "__main__":
    main()
