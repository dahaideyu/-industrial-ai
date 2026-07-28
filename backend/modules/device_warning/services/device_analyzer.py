# cython: annotation_typing=False, infer_types=False, language_level=3
from modules.device_warning.ai_analysis.main import FactoryAIAnalyzer


def analyze_device(module: str = "all", hours: int = 24, device_id: str | None = None):
    """
    执行设备分析
    返回: (results, error_msg, status_code)
    """
    valid_modules = ["anomaly", "health", "fault", "energy", "all"]
    if module not in valid_modules:
        return None, f"不支持的分析模块: {module}，可用模块: {valid_modules}", 400

    try:
        analyzer = FactoryAIAnalyzer(".")

        if module == "all":
            print(f"[调试] 执行完整分析...")
            results = analyzer.run_all(hours=hours)
        else:
            print(f"[调试] 执行 {module} 模块分析...")
            analyzer.load_data(hours=hours)

            if module == "anomaly":
                results = {"anomaly": analyzer.run_anomaly_detection()}
            elif module == "health":
                results = {"health": analyzer.run_health_dashboard()}
            elif module == "fault":
                results = {"fault": analyzer.run_fault_prediction()}
            elif module == "energy":
                results = {"energy": analyzer.run_energy_optimization()}

        print(f"[调试] 分析完成")
        return results, None, 200

    except FileNotFoundError as e:
        error_msg = f"数据文件未找到: {str(e)}"
        print(f"[错误] {error_msg}")
        return None, error_msg, 404

    except Exception as e:
        error_msg = f"分析失败: {str(e)}"
        print(f"[错误] {error_msg}")
        import traceback
        traceback.print_exc()
        return None, error_msg, 500
