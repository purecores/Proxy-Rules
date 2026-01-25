import subprocess
from pathlib import Path

# 固定配置
MIHOMO_EXE = Path(r"D:\APP\mihomo\mihomo.exe")
PERSONALUSE_DIR = Path("./personaluse")
RULE_TYPE = "domain"

# 需要编译的 yaml 文件
TARGET_YAML_FILES = [
    "personaluse-d.yaml",
    "personaluse-p.yaml",
]


def main():
    if not MIHOMO_EXE.exists():
        raise FileNotFoundError(f"mihomo.exe 不存在: {MIHOMO_EXE}")

    if not PERSONALUSE_DIR.exists():
        raise FileNotFoundError(f"personaluse 目录不存在: {PERSONALUSE_DIR}")

    for yaml_name in TARGET_YAML_FILES:
        yaml_file = PERSONALUSE_DIR / yaml_name

        if not yaml_file.exists():
            print(f"✘ 未找到文件: {yaml_file}")
            continue

        output_file = yaml_file.with_suffix(".mrs")

        cmd = [
            str(MIHOMO_EXE),
            "convert-ruleset",
            RULE_TYPE,
            "yaml",
            str(yaml_file),
            str(output_file)
        ]

        print(f"正在编译: {yaml_file.name}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            print(f"✔ 编译成功: {output_file.name}")
            if result.stdout:
                print(result.stdout)

        except subprocess.CalledProcessError as e:
            print(f"✘ 编译失败: {yaml_file.name}")
            if e.stderr:
                print(e.stderr)


if __name__ == "__main__":
    main()
