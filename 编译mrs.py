import subprocess
from pathlib import Path

# 固定配置
MIHOMO_EXE = Path(r"D:\APP\mihomo\mihomo.exe")
YAML_DIR = Path(r"D:\Code\Momo\mihomo")
RULE_TYPE = "domain"


def main():
    if not MIHOMO_EXE.exists():
        raise FileNotFoundError(f"mihomo.exe 不存在: {MIHOMO_EXE}")

    if not YAML_DIR.exists():
        raise FileNotFoundError(f"YAML 目录不存在: {YAML_DIR}")

    yaml_files = list(YAML_DIR.glob("*.yaml")) + list(YAML_DIR.glob("*.yml"))

    if not yaml_files:
        print("未找到任何 yaml 规则集文件")
        return

    for yaml_file in yaml_files:
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
