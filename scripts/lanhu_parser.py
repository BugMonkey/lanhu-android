#!/usr/bin/env python3
"""
蓝湖 Sketch JSON 解析脚本
从蓝湖导出的JSON中提取结构化标注、切图清单和阻塞记录
"""

import json
import io
import os
import re
import shutil
import sys
import subprocess
import argparse
import gzip
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


def fetch_url_bytes(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 60) -> bytes:
    """Fetch CDN bytes with httpx, urllib and curl fallbacks."""
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        request_headers.update(headers)

    errors: List[str] = []

    if HAS_HTTPX:
        try:
            with httpx.Client(headers=request_headers, timeout=timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except Exception as exc:
            errors.append(f"httpx: {exc}")

    try:
        request = Request(url, headers=request_headers)
        response = urlopen(request, timeout=timeout)
        return response.read()
    except Exception as exc:
        errors.append(f"urllib: {exc}")

    curl_cmd = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--connect-timeout",
        str(min(timeout, 30)),
        "--max-time",
        str(timeout),
    ]
    for key, value in request_headers.items():
        curl_cmd.extend(["-H", f"{key}: {value}"])
    curl_cmd.append(url)

    try:
        result = subprocess.run(curl_cmd, capture_output=True, timeout=timeout + 5)
        if result.returncode == 0:
            return result.stdout
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        errors.append(f"curl({result.returncode}): {stderr}")
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"curl: {exc}")

    raise URLError("; ".join(errors))


def persist_source_json(output_dir: Path, json_source_path: str, original_url: Optional[str] = None,
                        design_id: Optional[str] = None) -> Optional[Path]:
    """Persist the source design JSON into extract_dir for later safe inspection."""
    try:
        source_path = Path(json_source_path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        raw_json_path = output_dir / "raw.json"
        if source_path.resolve() != raw_json_path.resolve():
            shutil.copyfile(source_path, raw_json_path)

        source_meta = {
            "extract_dir": str(output_dir),
            "design_id": design_id or output_dir.name,
            "raw_json": str(raw_json_path),
            "json_source_path": str(source_path),
            "original_url": original_url or "",
        }
        with open(output_dir / "source_meta.json", "w", encoding="utf-8") as f:
            json.dump(source_meta, f, ensure_ascii=False, indent=2)

        print(f"原始 JSON 已保存: {raw_json_path}")
        return raw_json_path
    except Exception as exc:
        print(f"保存原始 JSON 失败: {exc}")
        return None


def _ensure_pillow():
    """强制安装 Pillow，安装失败则终止脚本"""
    try:
        from PIL import Image
        return True
    except ImportError:
        pass
    print("正在安装 Pillow (切图缩放依赖)...")
    for cmd in [
        [sys.executable, '-m', 'pip', 'install', '--user', 'Pillow'],
        [sys.executable, '-m', 'pip', 'install', '--break-system-packages', 'Pillow'],
    ]:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            try:
                from PIL import Image
                print("Pillow 安装成功")
                return True
            except ImportError:
                pass
    print("ERROR: Pillow 安装失败，请手动执行: pip install Pillow")
    sys.exit(1)


# ==================== 数据模型 ====================

@dataclass
class TextSegmentStyle:
    """文本分段样式（富文本单个分段的样式）"""
    content: str = ""           # 分段文本内容
    start: int = 0              # 分段起始位置
    end: int = 0                # 分段结束位置
    fontSize: float = 0.0       # 字号 (sp)
    fontFamily: str = ""        # 字体名称 (如 PingFangSC-Regular)
    fontWeight: int = 400       # 字重 (400=Regular, 500=Medium, 600+=Bold)
    color: str = "#000000"      # 颜色
    lineHeight: float = 0.0     # 行高


@dataclass
class TextStyle:
    """文本样式"""
    content: str = ""
    fontSize: float = 0.0
    fontWeight: int = 400
    color: str = "#000000"
    lineHeight: float = 0.0
    letterSpacing: float = 0.0
    fontFamily: str = ""
    textAlign: str = "left"
    # 富文本分段样式列表（每个分段可能有不同的颜色/字重）
    segments: List['TextSegmentStyle'] = field(default_factory=list)


@dataclass
class BoxStyle:
    """盒子样式"""
    width: float = 0
    height: float = 0
    margin: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    padding: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    backgroundColor: Optional[str] = None
    borderRadius: float = 0.0
    borderTopLeftRadius: float = 0.0
    borderTopRightRadius: float = 0.0
    borderBottomLeftRadius: float = 0.0
    borderBottomRightRadius: float = 0.0
    borderWidth: float = 0.0
    borderColor: Optional[str] = None
    shadow: Optional[Dict] = None
    opacity: float = 1.0


@dataclass
class SliceInfo:
    """切图信息（用于组件节点）"""
    name: str = ""                          # 切图文件名
    local_path: str = ""                    # 本地相对路径（相对于assets目录）
    drawable_name: str = ""                 # Android drawable 资源名（不含扩展名）
    size: str = ""                          # 尺寸
    status: str = "available"               # available | missing


@dataclass
class ComponentNode:
    """组件节点"""
    type: str = ""
    name: str = ""
    layerId: str = ""
    parentId: Optional[str] = None
    style: BoxStyle = field(default_factory=BoxStyle)
    text: Optional[TextStyle] = None
    slice: Optional[SliceInfo] = None       # 切图信息
    states: Dict = field(default_factory=dict)
    children: List['ComponentNode'] = field(default_factory=list)
    position: Dict = field(default_factory=lambda: {"x": 0, "y": 0})
    orientation: str = ""                   # 子元素排列方向: "vertical" | "horizontal" | ""
    sibling_gap: Dict = field(default_factory=dict)  # 与兄弟元素的间距: {"above": 9, "below": 10}


@dataclass
class SliceItem:
    """切图项"""
    name: str
    format: str = "png"
    density: str = "xxhdpi"
    size: str = ""                          # 标注尺寸 (原始尺寸)
    actual_size: str = ""                   # 实际尺寸 (标注尺寸 / sliceScale)
    source_layer: str = ""
    node_id: str = ""                       # 来源节点 ID（切图→节点映射的唯一依据）
    node_x: float = 0.0                     # 来源节点 x（dp，绝对坐标；同名图层去歧义）
    node_y: float = 0.0                     # 来源节点 y（dp，绝对坐标）
    ancestor_path: str = ""                 # 祖先链（如 "标签栏/交易/icon"），供人工核对归属
    download_url: str = ""
    svg_url: str = ""
    local_path: str = ""                    # 本地相对路径
    drawable_name: str = ""                 # Android drawable 资源名
    status: str = "available"
    scale: float = 1.0                      # sliceScale 缩放因子


@dataclass
class IssueItem:
    """阻塞/反馈项"""
    type: str  # 标注缺失 | 标注歧义 | 切图缺失
    screen: str
    layer: str
    description: str
    workaround: Optional[str] = None


# ==================== 蓝湖 API 客户端 ====================

class LanhuAPIClient:
    """
    蓝湖 API 客户端，提取自 MCP 源码
    支持直接通过蓝湖项目 URL 获取设计图数据
    """

    BASE_URL = "https://lanhuapp.com"
    DDS_BASE_URL = "https://dds.lanhuapp.com"

    def __init__(self, cookie: str = None):
        """
        初始化 API 客户端

        Args:
            cookie: 蓝湖登录 Cookie（可选，部分公开项目可能不需要）
        """
        self.cookie = cookie or os.getenv('LANHU_COOKIE', '')
        self._sync_client = None

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        if self.cookie:
            headers['Cookie'] = self.cookie
        return headers

    def _get_sync_client(self):
        """获取同步 HTTP 客户端"""
        if self._sync_client is None:
            if HAS_HTTPX:
                self._sync_client = httpx.Client(
                    headers=self._get_headers(),
                    timeout=30.0,
                    follow_redirects=True
                )
            else:
                # 使用 urllib 作为后备
                self._sync_client = 'urllib'
        return self._sync_client

    def _request(self, url: str) -> Dict:
        """发送同步请求"""
        client = self._get_sync_client()
        if client == 'urllib':
            content = fetch_url_bytes(url, headers=self._get_headers(), timeout=30)
            return json.loads(content.decode('utf-8'))
        else:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def parse_url(self, url: str) -> Dict:
        """
        解析蓝湖 URL，提取 team_id, project_id, doc_id, version_id

        支持多种格式：
        - https://lanhuapp.com/web/#/item/project/product?tid=...&pid=...&docId=...
        - https://lanhuapp.com/web/#/item/project/stage?tid=...&pid=...
        - https://lanhuapp.com/link/#/invite?sid=... (邀请链接)

        Returns:
            dict: {team_id, project_id, doc_id, version_id, url_type}
        """
        result = {
            'team_id': None,
            'project_id': None,
            'doc_id': None,
            'version_id': None,
            'url_type': None,  # 'product' | 'stage' | 'invite'
            'original_url': url
        }

        # 处理邀请链接
        if '/invite' in url:
            result['url_type'] = 'invite'
            # 需要额外处理，返回原始 URL 供后续解析
            return result

        # 解析 URL 参数
        parsed = urlparse(url)
        fragment = parsed.fragment  # 获取 # 后的部分

        # 从 fragment 中提取参数
        if '?' in fragment:
            query_part = fragment.split('?')[1]
            params = parse_qs(query_part)

            result['team_id'] = params.get('tid', [None])[0]
            result['project_id'] = params.get('pid', [None])[0]
            result['doc_id'] = params.get('docId', [None])[0]
            result['version_id'] = params.get('versionId', [None])[0]

            # 判断 URL 类型
            if '/product' in fragment:
                result['url_type'] = 'product'
            elif '/stage' in fragment:
                result['url_type'] = 'stage'

        return result

    def resolve_invite_link(self, invite_url: str) -> Dict:
        """
        解析邀请链接，获取实际项目 URL

        Args:
            invite_url: 邀请链接，如 https://lanhuapp.com/link/#/invite?sid=xxx

        Returns:
            dict: 解析后的项目信息
        """
        parsed = urlparse(invite_url)
        fragment = parsed.fragment
        params = parse_qs(fragment.split('?')[1] if '?' in fragment else '')

        sid = params.get('sid', [None])[0]
        if not sid:
            raise ValueError("邀请链接缺少 sid 参数")

        # 请求邀请链接解析接口
        resolve_url = f"{self.BASE_URL}/api/url/link?short_id={sid}"
        try:
            data = self._request(resolve_url)
            # 返回实际的项目 URL 信息
            return {
                'team_id': data.get('team_id'),
                'project_id': data.get('project_id'),
                'doc_id': data.get('doc_id'),
                'resolved_url': data.get('url'),
                'url_type': data.get('type', 'stage')
            }
        except Exception as e:
            raise ValueError(f"解析邀请链接失败: {e}")

    def get_designs(self, team_id: str, project_id: str) -> List[Dict]:
        """
        获取设计图列表

        Args:
            team_id: 团队 ID
            project_id: 项目 ID

        Returns:
            list: 设计图列表，每项包含 {id, name, url, json_url, cover_url}
        """
        url = f"{self.BASE_URL}/api/project/images?project_id={project_id}&team_id={team_id}&dds_status=1"

        try:
            data = self._request(url)
            designs = []

            for item in data.get('data', []) or data.get('images', []):
                designs.append({
                    'id': item.get('image_id') or item.get('id'),
                    'name': item.get('name') or item.get('image_name', 'Unknown'),
                    'url': item.get('url'),  # 设计图截图 URL
                    'json_url': item.get('json_url'),  # Sketch JSON URL
                    'cover_url': item.get('cover_url') or item.get('url'),
                    'width': item.get('width', 0),
                    'height': item.get('height', 0),
                })

            return designs
        except Exception as e:
            print(f"获取设计图列表失败: {e}")
            return []

    def get_design_detail(self, image_id: str, team_id: str, project_id: str) -> Dict:
        """
        获取设计图详情

        Args:
            image_id: 设计图 ID
            team_id: 团队 ID
            project_id: 项目 ID

        Returns:
            dict: {id, name, url, json_url, width, height}
        """
        url = f"{self.BASE_URL}/api/project/image?image_id={image_id}&team_id={team_id}&project_id={project_id}"

        try:
            data = self._request(url)
            return {
                'id': data.get('image_id') or data.get('id'),
                'name': data.get('name') or data.get('image_name', 'Unknown'),
                'url': data.get('url'),  # 设计图截图 PNG
                'json_url': data.get('json_url'),  # Sketch JSON 数据
                'width': data.get('width', 0),
                'height': data.get('height', 0),
                'dds_status': data.get('dds_status', 0),
            }
        except Exception as e:
            print(f"获取设计图详情失败: {e}")
            return {}

    def get_sketch_json(self, json_url: str) -> Dict:
        """
        下载 Sketch JSON 数据

        Args:
            json_url: JSON 数据 URL

        Returns:
            dict: Sketch JSON 数据
        """
        try:
            client = self._get_sync_client()
            if client == 'urllib':
                content = fetch_url_bytes(json_url, headers=self._get_headers(), timeout=60)
                return json.loads(content.decode('utf-8'))
            else:
                response = client.get(json_url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"下载 Sketch JSON 失败: {e}")
            return {}

    def get_project_info(self, team_id: str, project_id: str) -> Dict:
        """
        获取项目信息

        Args:
            team_id: 团队 ID
            project_id: 项目 ID

        Returns:
            dict: 项目信息
        """
        url = f"{self.BASE_URL}/api/project/multi_info?project_id={project_id}&team_id={team_id}"

        try:
            data = self._request(url)
            return {
                'name': data.get('name') or data.get('project_name', 'Unknown'),
                'type': data.get('type', 'unknown'),
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
            }
        except Exception as e:
            print(f"获取项目信息失败: {e}")
            return {}

    def close(self):
        """关闭客户端"""
        if self._sync_client and self._sync_client != 'urllib':
            self._sync_client.close()
            self._sync_client = None


# ==================== 工具函数 ====================

def parse_color(color_data: Any) -> Optional[str]:
    """解析颜色数据，返回 Android 可直接使用的 #RRGGBB 或 #AARRGGBB 格式"""
    if not color_data:
        return None

    # 字符串格式 "rgba(r,g,b,a)"
    if isinstance(color_data, str):
        match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', color_data)
        if match:
            r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
            a = float(match.group(4)) if match.group(4) else 1.0
            if a < 1.0:
                return f"#{int(round(a*255)):02X}{r:02X}{g:02X}{b:02X}"
            return f"#{r:02X}{g:02X}{b:02X}"
        return color_data

    # 对象格式 {r, g, b, a} 或 {red, green, blue, alpha} - 值范围 0-1 或 0-255
    if isinstance(color_data, dict):
        # 优先使用 value 字段（蓝湖 JSON 中 r/g/b/a 可能错误，value 字段更可靠）
        value_str = color_data.get('value', '')
        if value_str and isinstance(value_str, str):
            match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', value_str)
            if match:
                r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
                a = float(match.group(4)) if match.group(4) else 1.0
                if a < 1.0:
                    return f"#{int(round(a*255)):02X}{r:02X}{g:02X}{b:02X}"
                return f"#{r:02X}{g:02X}{b:02X}"

        # fallback: 使用 r/g/b/a 字段（判断值范围）
        r = color_data.get('r', color_data.get('red', 0))
        g = color_data.get('g', color_data.get('green', 0))
        b = color_data.get('b', color_data.get('blue', 0))
        a = color_data.get('a', color_data.get('alpha', 1))

        # 如果值大于1，说明是0-255范围
        if r > 1 or g > 1 or b > 1:
            r, g, b = int(r), int(g), int(b)
        else:
            r, g, b = int(r * 255), int(g * 255), int(b * 255)

        if a > 1:
            a = a / 255 if a <= 255 else 1.0

        if a < 1.0:
            return f"#{int(round(a*255)):02X}{r:02X}{g:02X}{b:02X}"
        return f"#{r:02X}{g:02X}{b:02X}"

    return None


def parse_font_weight(font_name: str) -> int:
    """
    从字体名称解析 fontWeight

    Args:
        font_name: 字体名称，如 "PingFangSC-Regular", "PingFangSC-Medium", "PingFangSC-Semibold"

    Returns:
        fontWeight 数值: 100-900

    常见映射:
        - Thin/Light: 100-300
        - Regular: 400
        - Medium: 500
        - SemiBold: 600
        - Bold: 700
        - ExtraBold/Black: 800-900
    """
    if not font_name:
        return 400

    font_lower = font_name.lower()

    # 常见字重关键词映射
    weight_keywords = {
        'thin': 100,
        'light': 300,
        'regular': 400,
        'normal': 400,
        'medium': 500,
        'semibold': 600,
        'semibold': 600,
        'bold': 700,
        'extrabold': 800,
        'black': 900,
        'heavy': 900,
    }

    for keyword, weight in weight_keywords.items():
        if keyword in font_lower:
            return weight

    # 默认返回 Regular (400)
    return 400


def round_metric(value: Any, digits: int = 2) -> float:
    """Normalize numeric metrics for JSON output while preserving decimals."""
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(numeric, digits)


def has_meaningful_value(value: Any, tolerance: float = 1e-6) -> bool:
    """Return True when a metric is meaningfully non-zero."""
    try:
        return abs(float(value or 0)) > tolerance
    except (TypeError, ValueError):
        return False


def apply_opacity_to_color(hex_color: str, opacity: float) -> str:
    """将图层级 opacity 合并到颜色 hex 值中。

    如果 hex 已是 #AARRGGBB（8位），说明 parse_color 已嵌入 alpha，
    不再叠加，直接返回原值。这是为了处理 parse_color 产出的 alpha
    （来自 fill color 内部的 a 字段）与图层级 opacity 共存的情况。

    Args:
        hex_color: 颜色 hex 值，如 "#RRGGBB" 或 "#AARRGGBB"
        opacity: 图层级透明度，范围 0.0-1.0

    Returns:
        合成后的颜色 hex 值，格式为 #AARRGGBB（含透明度时）或 #RRGGBB（无透明度时）
    """
    if not hex_color:
        return hex_color
    # 已是 #AARRGGBB（8位），说明 parse_color 已嵌入 alpha，不叠加
    if len(hex_color) == 9 and hex_color.startswith('#'):
        return hex_color
    # opacity 为 1.0 时直接返回原值
    if opacity >= 1.0:
        return hex_color
    a = int(round(opacity * 255))
    return f"#{a:02X}{hex_color.lstrip('#')}"


def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    # 移除或替换非法字符
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip()
    return name


def write_json_file(path: Path, data: Any, indent: int = 1):
    """写 JSON 文件并确保父目录存在"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def design_id_from_source(source_path: str) -> Optional[str]:
    """Return the same stable design_id used by the parsers for URL/local inputs."""
    if not source_path:
        return None
    if source_path.startswith('http'):
        url_path = source_path.split('/')[-1]
        design_id = url_path.replace('.json', '').replace('.gzip', '')
        if len(design_id) > 30:
            design_id = design_id[:30]
        return sanitize_filename(design_id)
    return sanitize_filename(Path(source_path).stem)


def get_cached_extract_dir(output_dir: str, source_path: str) -> Optional[Path]:
    design_id = design_id_from_source(source_path)
    if not design_id:
        return None
    return Path(output_dir).expanduser() / design_id


def missing_extract_outputs(extract_dir: Path, require_screenshot: bool = False) -> List[str]:
    required = ["annotations.json", "slices.json", "layout_analysis.json"]
    if require_screenshot:
        required.append("screenshot.png")

    missing = []
    for filename in required:
        path = extract_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            missing.append(filename)
    return missing


def can_reuse_extract(extract_dir: Optional[Path], require_screenshot: bool = False) -> Tuple[bool, List[str]]:
    if not extract_dir or not extract_dir.exists() or not extract_dir.is_dir():
        return False, ["extract_dir"]
    missing = missing_extract_outputs(extract_dir, require_screenshot=require_screenshot)
    return not missing, missing


def reuse_existing_extract_if_complete(output_dir: str, source_path: str, screenshot_source: Optional[str],
                                       force_refresh: bool = False) -> bool:
    """Reuse a complete extract directory before downloading the same large JSON again."""
    if force_refresh:
        print("已指定 --force-refresh，跳过本地缓存复用")
        return False

    extract_dir = get_cached_extract_dir(output_dir, source_path)
    if not extract_dir:
        return False

    ok, missing = can_reuse_extract(extract_dir, require_screenshot=bool(screenshot_source))
    if not ok and screenshot_source and missing == ["screenshot.png"]:
        saved = save_screenshot_resource(extract_dir, screenshot_source)
        if saved:
            ok, missing = can_reuse_extract(extract_dir, require_screenshot=True)

    if ok:
        print(f"复用已存在的蓝湖提取产物: {extract_dir}")
        print("如需重新下载 JSON/截图/切图，请添加 --force-refresh")
        return True

    if extract_dir.exists():
        print(f"发现缓存但产物不完整，重新提取: {extract_dir} 缺失 {', '.join(missing)}")
    return False


def slice_scale_warning(slice_scale: float) -> str:
    return (
        f"CDN 下载 URL 返回的切图尺寸 = 设计尺寸 × sliceScale({slice_scale})，"
        "手动下载会拿到放大后的尺寸。使用本脚本的 download_slices() 会自动缩放回 "
        "actual_size。如需手动下载，务必按 actual_size 字段 resize。"
    )


def _parse_slice_dp(actual_size: str) -> Tuple[Optional[float], Optional[float]]:
    """从 actual_size 解析出 width_dp/height_dp（xxhdpi=3.0）。

    Args:
        actual_size: 实际尺寸字符串，如 "120x80"

    Returns:
        (width_dp, height_dp) 元组，解析失败返回 (None, None)
    """
    if not actual_size:
        return None, None
    try:
        parts = actual_size.split('x')
        if len(parts) != 2:
            return None, None
        w_px, h_px = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None, None
    # xxhdpi = 3.0
    density = 3.0
    return round(w_px / density, 2), round(h_px / density, 2)


def save_slices_file(output_dir: Path, slices: List['SliceItem'], slice_scale: float):
    slices_file = output_dir / "slices.json"
    # 为每条 slice 添加 width_dp/height_dp 字段
    slices_data = []
    for s in slices:
        slice_dict = asdict(s)
        width_dp, height_dp = _parse_slice_dp(s.actual_size)
        if width_dp is not None and height_dp is not None:
            slice_dict["width_dp"] = width_dp
            slice_dict["height_dp"] = height_dp
        slices_data.append(slice_dict)
    write_json_file(slices_file, {
        "_slice_scale_warning": slice_scale_warning(slice_scale),
        "slices": slices_data,
    })
    print(f"切图清单已保存: {slices_file}")


def save_issues_file(output_dir: Path, issues: List['IssueItem']):
    issues_file = output_dir / "issues.json"
    write_json_file(issues_file, {"issues": [asdict(i) for i in issues]})
    print(f"阻塞记录已保存: {issues_file}")


def build_layout_analysis_payload(parser_instance: Any, screenshot_path: Optional[str]) -> Dict:
    legacy_analysis = getattr(parser_instance, "layout_analysis", {}) or {}
    has_screenshot = bool(screenshot_path and Path(screenshot_path).exists())
    design_id = getattr(parser_instance, "design_id", None) or getattr(parser_instance, "artboard_name", "unknown")
    source_json = getattr(parser_instance, "original_url", None) or getattr(parser_instance, "json_path", "") or ""

    implementation_hints = []
    if legacy_analysis:
        implementation_hints.append({
            "scope": "xml",
            "message": "基础布局语义见 annotations.json.layoutAnalysis。",
            "priority": "medium",
        })

    risk_flags = []
    if not has_screenshot:
        risk_flags.append({
            "code": "missing_screenshot",
            "severity": "medium",
            "message": "未生成 screenshot.png，只能做低置信度结构分析。",
            "blocked": False,
        })
    else:
        risk_flags.append({
            "code": "missing_visual_review",
            "severity": "medium",
            "message": "已生成 screenshot.png，但尚未完成截图级读图分析，当前 layout_analysis.json 仅为脚本占位结果。",
            "blocked": False,
        })

    return {
        "schema_version": "1.0",
        "design_id": str(design_id),
        "source": {
            "json": str(source_json),
            "screenshot": str(screenshot_path or ""),
        },
        "confidence": "low",
        "layout_summary": "脚本生成的基础布局分析；如需高还原度，请结合截图分析补全。",
        "screen_type": "unknown",
        "screenshot_review": {
            "viewed": False,
            "viewer": "unknown",
            "coverage": [],
            "evidence": [],
            "limitations": [
                "当前文件仅为 extract 阶段的基础占位，尚未通过读图子 agent 完成视觉理解。"
            ],
        },
        "user_intent": {
            "source": "not_provided",
            "request_summary": "",
            "requested_screen_type": "unknown",
            "core_requirements": [],
            "explicit_inclusions": [],
            "explicit_exclusions": [],
            "interaction_requirements": [],
            "data_regions": [],
            "notes": "脚本只生成基础占位；用户意图由调用方在读图分析阶段补全。",
        },
        "android_layout_assumptions": [],
        "confirmation_items": [],
        "root_layout_recommendation": {
            "type": "ConstraintLayout",
            "reason": "默认适配复杂设计稿层级，具体结构需结合截图确认。",
        },
        "sections": [],
        "fixed_regions": [],
        "scroll_strategy": {
            "type": "none",
            "scroll_region": "",
            "fixed_outside_scroll": [],
            "reason": "脚本未可靠判断滚动结构。",
        },
        "element_classification": [],
        "background_layers": [],
        "component_groups": [],
        "constraint_hints": [],
        "implementation_hints": implementation_hints,
        "risk_flags": risk_flags,
    }


def save_layout_analysis_file(parser_instance: Any, screenshot_path: Optional[str]):
    layout_file = parser_instance.output_dir / "layout_analysis.json"
    write_json_file(layout_file, build_layout_analysis_payload(parser_instance, screenshot_path))
    print(f"布局分析已保存: {layout_file}")


SCREENSHOT_MAX_WIDTH = 540  # 截图等比例缩放最大宽度


def resize_image_to_max_width(image_path: Path, max_width: int = SCREENSHOT_MAX_WIDTH) -> bool:
    """将图片等比例缩放到 max_width 宽度。返回 True 表示已缩放。"""
    try:
        from PIL import Image
    except ImportError:
        return False

    try:
        img = Image.open(image_path)
        if img.width <= max_width:
            return False

        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img_resized = img.resize((max_width, new_h), Image.LANCZOS)
        img_resized.save(image_path, format="PNG")
        print(f"截图已压缩: {img.width}x{img.height} -> {max_width}x{new_h}")
        return True
    except Exception as e:
        print(f"截图压缩失败: {e}")
        return False


def save_screenshot_resource(output_dir: Path, screenshot_source: str) -> Optional[str]:
    if not screenshot_source:
        return None

    screenshot_path = output_dir / "screenshot.png"
    try:
        if screenshot_source.startswith("http"):
            headers = {
                "Referer": "https://lanhuapp.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image,*/*;q=0.8",
            }
            data = fetch_url_bytes(screenshot_source, headers=headers, timeout=60)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            with open(screenshot_path, "wb") as f:
                f.write(data)
        else:
            source_path = Path(screenshot_source).expanduser()
            if not source_path.exists():
                raise FileNotFoundError(str(source_path))
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.resolve() != screenshot_path.resolve():
                shutil.copyfile(source_path, screenshot_path)

        # 等比例压缩到 SCREENSHOT_MAX_WIDTH
        resize_image_to_max_width(screenshot_path)

        print(f"页面截图已保存: {screenshot_path}")
        return str(screenshot_path)
    except Exception as e:
        print(f"保存页面截图失败: {e}")
        return None


def _ensure_unique_slice_paths(slices: List[SliceItem]):
    """同 local_path 不同 download_url 的 slice 按 node_id 改名，消除覆盖写。"""
    seen: Dict[str, str] = {}
    for s in slices:
        if s.local_path not in seen:
            seen[s.local_path] = s.download_url
            continue
        if seen[s.local_path] == s.download_url:
            continue
        directory, _, _ = s.local_path.rpartition('/')
        stem, dot, ext = s.name.rpartition('.')
        if not dot:
            stem, ext = s.name, 'png'
        suffix = (s.node_id or '')[:8].lower() or 'dup'
        s.name = f"{stem}_{suffix}.{ext}"
        s.drawable_name = s.name.rsplit('.', 1)[0]
        s.local_path = f"{directory}/{s.name}"
        seen[s.local_path] = s.download_url


def download_slice_assets(parser_instance: Any, max_workers: int = 5):
    """下载切图并更新 slices / issues 状态。"""
    slices = parser_instance.slices
    if not slices:
        print("没有切图需要下载")
        return

    _ensure_unique_slice_paths(slices)
    if any(s.scale != 1.0 and s.format == 'png' and s.actual_size for s in slices):
        _ensure_pillow()
        from PIL import Image
    else:
        Image = None

    failures: List[Tuple[SliceItem, str]] = []

    def download_slice(slice_item: SliceItem) -> Tuple[bool, str]:
        target_path = parser_instance.output_dir / slice_item.local_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = fetch_url_bytes(slice_item.download_url, timeout=30)

            if Image and slice_item.scale != 1.0 and slice_item.format == 'png' and slice_item.actual_size:
                w, h = map(int, slice_item.actual_size.split('x'))
                img = Image.open(io.BytesIO(data))
                if img.width != w or img.height != h:
                    img_resized = img.resize((w, h), Image.LANCZOS)
                    buffer = io.BytesIO()
                    img_resized.save(buffer, format='PNG')
                    data = buffer.getvalue()
                    print(f"缩放切图: {slice_item.name} ({img.width}x{img.height} -> {w}x{h})")

            with open(target_path, 'wb') as f:
                f.write(data)

            print(f"下载成功: {slice_item.name}")
            return True, ""
        except Exception as e:
            error = str(e)
            print(f"下载失败: {slice_item.name} - {error}")
            slice_item.status = "missing"
            return False, error

    print(f"开始下载 {len(slices)} 个切图...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_slice, s): s for s in slices}
        for future in as_completed(futures):
            ok, error = future.result()
            if not ok:
                failures.append((futures[future], error))

    if failures and hasattr(parser_instance, "issues"):
        screen = getattr(parser_instance, "artboard_name", None)
        if not screen and getattr(parser_instance, "annotations", None):
            screen = next(iter(parser_instance.annotations.keys()))
        for slice_item, error in failures:
            parser_instance.issues.append(IssueItem(
                type="切图下载失败",
                screen=screen or "",
                layer=slice_item.source_layer or slice_item.name,
                description=f"{slice_item.name} 下载失败: {error}",
                workaround="保留 slices.json 记录，后续可重新运行 extract 或手动补充资源。",
            ))

    print("切图下载完成")


def sync_annotation_slice_status(parser_instance: Any):
    """把下载后的切图状态同步回 annotations 节点，避免 annotations 与 slices 不一致。"""
    slice_map = getattr(parser_instance, "slice_map", {}) or {}
    annotations = getattr(parser_instance, "annotations", {}) or {}
    if not slice_map or not annotations:
        return

    def visit(node: ComponentNode):
        slice_item = slice_map.get(node.layerId)
        if node.slice and slice_item:
            node.slice.status = slice_item.status
            node.slice.name = slice_item.name
            node.slice.local_path = slice_item.local_path
            node.slice.drawable_name = slice_item.drawable_name
            node.slice.size = slice_item.size
        for child in node.children:
            visit(child)

    for tree in annotations.values():
        visit(tree)


# 中英文映射表（常见图层名 -> 英文）
LAYER_NAME_MAP = {
    # 通用
    '矩形': 'rect',
    '椭圆形': 'oval',
    '圆形': 'circle',
    '直线': 'line',
    '路径': 'path',
    '三角形': 'triangle',
    '多边形': 'polygon',
    '星形': 'star',
    '蒙版': 'mask',
    '编组': 'group',
    '图层': 'layer',
    '背景': 'background',
    '前景': 'foreground',
    '阴影': 'shadow',
    '边框': 'border',
    '分割线': 'divider',
    '顶部状态栏': 'status_bar',
    '状态栏': 'status_bar',

    # 导航/Tab
    '首页': 'home',
    '首页备份': 'home',
    '订单': 'order',
    '我的': 'mine',
    '我的备份': 'mine',
    '优惠卡': 'coupon',
    '福利': 'welfare',
    '购物车': 'cart',
    '消息': 'message',
    '发现': 'discover',
    '搜索': 'search',
    '设置': 'setting',
    '个人中心': 'profile',

    # 按钮
    '按钮': 'btn',
    '提交': 'submit',
    '确认': 'confirm',
    '取消': 'cancel',
    '返回': 'back',
    '关闭': 'close',
    '删除': 'delete',
    '编辑': 'edit',
    '保存': 'save',
    '下一步': 'next',
    '上一步': 'prev',
    '登录': 'login',
    '注册': 'register',
    '进入': 'enter',
    '对话': 'chat',
    '点击查看': 'view_detail',
    '拍照查成分': 'scan_ingredient',

    # 商品相关
    '商品': 'product',
    '商品标题': 'product_title',
    '价格': 'price',
    '标签': 'tag',
    '角标': 'badge',
    '折扣': 'discount',
    '销量': 'sales',
    '已售': 'sold',
    '护肤品热门成分': 'hot_ingredients',
    '热门成分': 'hot_ingredients',
    '孕妇慎用成分': 'pregnancy_caution',
    '孕妇慎用': 'pregnancy_caution',
    '致痘成分': 'acne_ingredient',
    '维生素': 'vitamin',
    '甘油': 'glycerin',
    '保湿': 'moisturizing',
    '美白': 'whitening',
    '祛痘': 'anti_acne',
    '抗衰': 'anti_aging',
    '抗氧化': 'antioxidant',
    '抗氧': 'antioxidant',
    '防腐剂': 'preservative',

    # AI相关
    'ai': 'ai',
    '助手': 'assistant',
    '机器人': 'robot',

    # 状态
    '选中': 'selected',
    '未选中': 'normal',
    '禁用': 'disabled',
    '按下': 'pressed',
    '悬停': 'hover',
    '正常': 'normal',
}

# 功能关键词映射（用于从上下文推断功能）
CONTEXT_KEYWORD_MAP = {
    '首页': 'home',
    '订单': 'order',
    '我的': 'mine',
    '优惠卡': 'coupon',
    '福利': 'welfare',
    '购物车': 'cart',
    '消息': 'message',
    '发现': 'discover',
    '搜索': 'search',
    '设置': 'setting',
    '个人中心': 'profile',
    '返回': 'back',
    '关闭': 'close',
    '确认': 'confirm',
    '取消': 'cancel',
    '提交': 'submit',
    '删除': 'delete',
    '编辑': 'edit',
    '分享': 'share',
    '收藏': 'favorite',
    '点赞': 'like',
    '评论': 'comment',
    '刷新': 'refresh',
    '更多': 'more',
    '添加': 'add',
    '扫码': 'scan',
    '客服': 'service',
    '通知': 'notification',
    '时间': 'time',
    '日期': 'date',
    '位置': 'location',
    '电话': 'phone',
    '邮箱': 'email',
    '用户': 'user',
    '头像': 'avatar',
    '箭头': 'arrow',
    '三角形': 'triangle',
    '圆形': 'circle',
    '矩形': 'rect',
    '背景': 'bg',
    '护肤品热门成分': 'hot_ingredients',
    '热门成分': 'hot_ingredients',
    '孕妇慎用': 'pregnancy_caution',
    '致痘': 'acne_ingredient',
    '维生素': 'vitamin',
    '甘油': 'glycerin',
    '保湿': 'moisturizing',
    '美白': 'whitening',
    '祛痘': 'anti_acne',
    '抗衰': 'anti_aging',
    '抗氧': 'antioxidant',
    '防腐剂': 'preservative',
    '点击查看': 'view_detail',
    '拍照查成分': 'scan_ingredient',
}


def translate_layer_name(name: str) -> str:
    """将图层名翻译为英文"""
    name_lower = name.lower()

    # 如果已经是英文，直接处理
    if re.match(r'^[a-z0-9_]+$', name_lower):
        return name_lower

    # 尝试匹配中文映射
    for cn, en in LAYER_NAME_MAP.items():
        if cn in name:
            return en

    # 提取已有的英文部分
    english_parts = re.findall(r'[a-z0-9]+', name_lower)
    if english_parts:
        return '_'.join(english_parts)

    # 无法识别，使用hash
    import hashlib
    hash_val = hashlib.md5(name.encode()).hexdigest()[:6]
    return f'img_{hash_val}'


# 全局计数器，用于处理同名图层
_name_counter: Dict[str, int] = {}


def generate_slice_name(
    layer_name: str,
    context_info: Dict = None,
    layer_path: str = None,
    ensure_unique: bool = True,
    layer: Dict = None  # 新增：传入完整图层数据用于尺寸判断
) -> str:
    """
    根据图层名和路径生成切图文件名（Android命名规范）

    规则：
    - 前缀：ic_（图标）、bg_（背景）、btn_（按钮）、img_（图片）、divider_（分割线）
    - 全小写，下划线分隔
    - 描述使用英文，简洁明确
    - 状态后缀：_nor（正常）、_sel（选中）、_press（按下）、_dis（禁用）
    - 结合上下文推断功能命名（优先级最高）
    - 支持 layer_path 语义推断（如 "TopStatusBar/Battery/Border" → "status_bar_battery_border"）
    - 示例：ic_tab_home_sel.png、ic_tab_order_nor.png、bg_status_bar.png

    新增优化：
    - 优先从兄弟文本推断功能名称（如 "画质修复" → bg_card_quality.png）
    - 控制路径嵌套深度，避免 ic_group_group_group.png 这种模糊命名
    """
    global _name_counter

    if context_info is None:
        context_info = {}

    if layer is None:
        layer = {}

    # ===== 优先级 1：从兄弟文本推断功能名称（最高优先级）=====
    # 解决问题：ic_group_group_group_9.png → bg_card_quality.png
    sibling_texts = context_info.get('sibling_texts', [])
    nearby_text = context_info.get('nearby_text', '')

    # 功能卡片关键词映射（中文 → 英文语义）
    card_keywords = {
        '画质修复': 'card_quality',
        'AI消除': 'card_ai_erase',
        '智能抠图': 'card_smart_cut',
        '一键拼图': 'card_puzzle',
        '视频剪辑': 'card_video_edit',
        '监控瞬间集锦': 'banner_highlight',
        '前往查看': 'btn_goto',
        '直击现场，震撼呈现': 'banner_subtitle',
    }

    for text_info in sibling_texts:
        text = text_info.get('text', '')
        if text in card_keywords:
            keyword = card_keywords[text]

            # 判断是背景/按钮还是图标（根据尺寸）
            width = layer.get('width', 0)
            height = layer.get('height', 0)

            # 大面积矩形/组 → 背景
            if keyword.startswith('card_') or keyword.startswith('banner_'):
                if width > 100 or height > 100:
                    semantic_name = f"bg_{keyword}"
                else:
                    semantic_name = f"ic_{keyword}"
            # 按钮
            elif keyword.startswith('btn_'):
                semantic_name = keyword
            else:
                semantic_name = f"ic_{keyword}"

            final_name = f"{semantic_name}.png"

            # 处理同名冲突
            if ensure_unique:
                base_key = final_name.rsplit('.', 1)[0]
                if base_key in _name_counter:
                    _name_counter[base_key] += 1
                    final_name = f"{base_key}_{_name_counter[base_key]}.png"
                else:
                    _name_counter[base_key] = 1

            return final_name

    # ===== 优先级 1.5：泛化的邻近文本语义 =====
    # 蓝湖里常见 "编组/路径/矩形" 这类无语义图层，实际语义在旁边文本。
    semantic_from_text = None
    for text_info in sibling_texts[:3]:
        text = text_info.get('text', '')
        for cn, en in CONTEXT_KEYWORD_MAP.items():
            if cn in text:
                semantic_from_text = en
                break
        if semantic_from_text:
            break

    if not semantic_from_text and nearby_text:
        for cn, en in CONTEXT_KEYWORD_MAP.items():
            if cn in nearby_text:
                semantic_from_text = en
                break

    generic_layer_name = any(token in layer_name for token in ['编组', '矩形', '路径', '形状', '椭圆'])
    if semantic_from_text and generic_layer_name:
        width = layer.get('width', 0)
        height = layer.get('height', 0)
        if width >= 240 or height >= 160:
            prefix = 'bg_'
        elif width >= 120 or height >= 80:
            prefix = 'img_'
        else:
            prefix = 'ic_'
        final_name = f"{prefix}{semantic_from_text}.png"
        if ensure_unique:
            base_key = final_name.rsplit('.', 1)[0]
            if base_key in _name_counter:
                _name_counter[base_key] += 1
                final_name = f"{base_key}_{_name_counter[base_key]}.png"
            else:
                _name_counter[base_key] = 1
        return final_name

    # 状态映射（输出简短形式）
    state_map = {
        'sel': 'sel',
        'selected': 'sel',
        'nor': 'nor',
        'normal': 'nor',
        'press': 'press',
        'pressed': 'press',
        'dis': 'dis',
        'disabled': 'dis',
        'hover': 'hover',
        'active': 'press',
        'inactive': 'nor',
        'on': 'sel',
        'off': 'nor',
    }

    # 状态检测模式（增强版）
    state_patterns = [
        (r'_sel\b|_selected\b|选中', 'sel'),
        (r'_nor\b|_normal\b|正常|未选中', 'nor'),
        (r'_press\b|_pressed\b|按下|点击', 'press'),
        (r'_dis\b|_disabled\b|禁用', 'dis'),
        (r'_hover\b|悬停', 'hover'),
        (r'_on\b|开启', 'sel'),
        (r'_off\b|关闭', 'nor'),
    ]

    detected_state = None
    name_lower = layer_name.lower()

    # ===== 新增：从 layer_path 推断语义 =====
    semantic_from_path = None
    if layer_path:
        path_parts = layer_path.split('/')
        # 过滤无效部分，提取关键语义
        valid_parts = []
        for part in path_parts:
            part_lower = part.lower()
            # 跳过通用/无意义名称
            if part_lower in ['group', 'layer', 'rectangle', 'oval', 'shape', 'artboard', '画板', '编组', '图层']:
                continue
            # 翻译中文
            translated = translate_layer_name(part)
            if translated and not translated.startswith('img_'):
                valid_parts.append(translated)

        if valid_parts:
            # 取最后2-3个有效部分作为语义名
            semantic_parts = valid_parts[-3:] if len(valid_parts) > 3 else valid_parts
            semantic_from_path = '_'.join(semantic_parts)

    # ===== 新增：从父图层/兄弟图层推断状态 =====
    if not detected_state:
        parent_name = context_info.get('parent_name', '')
        parent_lower = parent_name.lower()

        # 从父图层名检测状态
        for pattern, state_val in state_patterns:
            if re.search(pattern, parent_lower):
                detected_state = state_val
                break

        # 从 layer_path 中的父级路径检测状态
        if not detected_state and layer_path:
            path_parts = layer_path.split('/')
            for part in path_parts[:-1]:  # 排除当前图层
                part_lower = part.lower()
                for pattern, state_val in state_patterns:
                    if re.search(pattern, part_lower):
                        detected_state = state_val
                        break
                if detected_state:
                    break

    # 从当前图层名检测状态
    if not detected_state:
        for pattern, state_val in state_patterns:
            if re.search(pattern, name_lower) or re.search(pattern, layer_name):
                detected_state = state_val
                break

    # 特殊处理：已规范的命名（如 icon_tab1_sel -> ic_tab1_sel）
    icon_match = re.match(r'^icon_(\w+)$', name_lower)
    if icon_match:
        parts_str = icon_match.group(1)
        # 清理末尾下划线
        parts_str = parts_str.rstrip('_')
        parts = parts_str.split('_') if parts_str else []

        # 检查最后一部分是否是状态
        if parts and parts[-1] in state_map:
            detected_state = state_map[parts[-1]]
            parts = parts[:-1]

        # 优先使用 layer_path 推断的语义
        base = semantic_from_path if semantic_from_path else None

        # 其次尝试从上下文推断功能
        if not base:
            nearby_text = context_info.get('nearby_text', '')
            for cn, en in CONTEXT_KEYWORD_MAP.items():
                if cn in nearby_text:
                    base = en
                    break

        # 最后使用原有部分
        if not base and parts:
            base = '_'.join(parts)

        if not base:
            base = 'unknown'

        if detected_state:
            final_name = f"ic_{base}_{detected_state}.png"
        elif base:
            final_name = f"ic_{base}.png"
        else:
            final_name = "ic_unknown.png"

        # 处理同名冲突
        if ensure_unique:
            base_key = final_name.rsplit('.', 1)[0]
            if base_key in _name_counter:
                _name_counter[base_key] += 1
                final_name = f"{base_key}_{_name_counter[base_key]}.png"
            else:
                _name_counter[base_key] = 1

        return final_name

    # 优先使用 layer_path 推断的语义名
    if semantic_from_path:
        english_name = semantic_from_path
    else:
        # 先尝试从图层名本身翻译
        english_name = translate_layer_name(layer_name)

    # 如果翻译结果是有效的（不是hash），优先使用
    if not english_name.startswith('img_') and english_name != 'unknown':
        # 确定前缀
        prefix = 'ic_'
        name_for_prefix = english_name if semantic_from_path else name_lower

        if english_name in ['bg', 'background'] or english_name.endswith('_bg') or '背景' in layer_name:
            prefix = 'bg_'
            if english_name not in ['bg', 'background'] and not english_name.endswith('_bg'):
                english_name = 'bg'
        elif 'btn' in name_for_prefix or 'button' in name_for_prefix or '按钮' in layer_name:
            prefix = 'btn_'
        elif 'divider' in name_for_prefix or '分割线' in layer_name:
            prefix = 'divider_'
        elif name_for_prefix.startswith('img_'):
            prefix = 'img_'

        # 清理名称
        english_name = re.sub(r'[^a-z0-9]', '_', english_name)
        english_name = re.sub(r'_+', '_', english_name).strip('_')

        width = layer.get('width', 0)
        height = layer.get('height', 0)
        if prefix == 'ic_' and (width >= 240 or height >= 160):
            prefix = 'bg_'
        elif prefix == 'ic_' and (width >= 120 or height >= 80):
            prefix = 'img_'

        if detected_state:
            final_name = f"{prefix}{english_name}_{detected_state}.png"
        elif english_name:
            final_name = f"{prefix}{english_name}.png"
        else:
            final_name = f"{prefix}unknown.png"

        final_name = re.sub(r'_+', '_', final_name)

        if ensure_unique:
            base_key = final_name.rsplit('.', 1)[0]
            if base_key in _name_counter:
                _name_counter[base_key] += 1
                final_name = f"{base_key}_{_name_counter[base_key]}.png"
            else:
                _name_counter[base_key] = 1

        return final_name

    # 检测状态（如果前面没检测到）
    if not detected_state:
        for pattern, state_val in state_patterns:
            if re.search(pattern, name_lower):
                detected_state = state_val
                name_lower = re.sub(pattern, '', name_lower)
                break

    # 翻译为英文
    if not semantic_from_path:
        english_name = translate_layer_name(layer_name)

    # 尝试从上下文推断功能
    context_keyword = None
    nearby_text = context_info.get('nearby_text', '')
    parent_name = context_info.get('parent_name', '')

    # 先检查父节点名称
    for cn, en in CONTEXT_KEYWORD_MAP.items():
        if cn in parent_name:
            context_keyword = en
            break

    # 再检查附近文本
    if not context_keyword:
        for cn, en in CONTEXT_KEYWORD_MAP.items():
            if cn in nearby_text:
                context_keyword = en
                break

    # 如果有上下文关键词，使用它
    if context_keyword:
        english_name = context_keyword

    # 确定前缀
    prefix = 'ic_'

    # 根据图层名特征判断前缀
    if english_name == 'bg' or name_lower == 'bg':
        prefix = 'bg_'
        english_name = 'bg'
    elif english_name.startswith('bg_'):
        prefix = 'bg_'
        english_name = english_name[3:]
    elif english_name.startswith('btn_'):
        prefix = 'btn_'
        english_name = english_name[4:]
    elif english_name.startswith('img_'):
        prefix = 'img_'
        english_name = english_name[4:]
    elif 'divider' in english_name:
        prefix = 'divider_'
        english_name = english_name.replace('divider', '')
    elif 'btn' in english_name or 'button' in english_name:
        prefix = 'btn_'
        english_name = english_name.replace('btn', '').replace('button', '')
    elif english_name.startswith('ic_'):
        prefix = 'ic_'
        english_name = english_name[3:]

    # 清理名称
    english_name = re.sub(r'[^a-z0-9]', '_', english_name)
    english_name = re.sub(r'_+', '_', english_name).strip('_')

    if not english_name:
        english_name = 'unknown'

    width = layer.get('width', 0)
    height = layer.get('height', 0)
    if prefix == 'ic_' and (width >= 240 or height >= 160):
        prefix = 'bg_'
    elif prefix == 'ic_' and (width >= 120 or height >= 80):
        prefix = 'img_'

    # 构建最终名称
    if detected_state:
        final_name = f"{prefix}{english_name}_{detected_state}.png"
    else:
        final_name = f"{prefix}{english_name}.png"

    # 最终清理
    final_name = re.sub(r'_+', '_', final_name)

    # 处理同名冲突
    if ensure_unique:
        base_key = final_name.rsplit('.', 1)[0]
        if base_key in _name_counter:
            _name_counter[base_key] += 1
            final_name = f"{base_key}_{_name_counter[base_key]}.png"
        else:
            _name_counter[base_key] = 1

    return final_name


def reset_name_counter():
    """重置名称计数器（处理新的画板时调用）"""
    global _name_counter
    _name_counter = {}


# ==================== JSON 格式检测 ====================

def detect_json_format(json_path: str = None, json_data: Dict = None) -> str:
    """
    检测 JSON 格式类型

    Returns:
        "figma" - Figma JSON 格式（来自 Figma 导出）
        "sketch" - Sketch JSON 格式（蓝湖原有格式）
    """
    # 优先从 URL 检测
    if json_path and json_path.startswith('http'):
        # URL 中包含 "FigmaJSON" 关键字
        if 'FigmaJSON' in json_path:
            return "figma"
        # 默认为 Sketch 格式
        return "sketch"

    # 从 JSON 结构检测
    if json_data:
        # Figma 格式特征：顶层有 meta/artboard/assets
        if 'artboard' in json_data and 'meta' in json_data:
            meta = json_data.get('meta', {})
            host = meta.get('host', {})
            if host.get('name') == 'figma':
                return "figma"

        # Sketch 格式特征：顶层有 pageName/info
        if 'pageName' in json_data and 'info' in json_data:
            return "sketch"

    # 尝试从文件内容检测
    if json_path and not json_path.startswith('http'):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                # 只读取前几行进行检测
                first_chars = f.read(500)
                f.seek(0)
                data = json.load(f)

                if 'artboard' in data and 'meta' in data:
                    return "figma"
                if 'pageName' in data and 'info' in data:
                    return "sketch"
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            # 文件读取或解析失败，使用默认格式
            pass

    # 默认返回 sketch 格式
    return "sketch"


# ==================== Figma JSON 解析器 ====================

class FigmaJsonParser:
    """
    Figma JSON 解析器（处理 Figma 导出的 JSON 格式）

    Figma JSON 结构特点：
    - 顶层：meta, assets, artboard
    - artboard.layers 是嵌套树形结构（每个图层可包含子 layers）
    - 图层类型：shapeLayer, textLayer, bitmapLayer, groupLayer
    - 样式在 style 对象内（fills, borders, shadows）
    - 文本在 text 对象内
    - 图片在 image 对象内（imageUrl, svgUrl）
    """

    def __init__(self, json_path: str = None, output_dir: str = "./output", json_data: Dict = None,
                 original_url: str = None):
        self.json_path = json_path
        self.original_url = original_url  # 保存原始 URL（下载场景下 json_path 会变成临时文件路径）
        self.output_dir = Path(output_dir)
        self._json_data = json_data
        self.data: Dict = {}

        # 输出结果
        self.annotations: Dict[str, ComponentNode] = {}
        self.slices: List[SliceItem] = []
        self.issues: List[IssueItem] = []
        self.slice_map: Dict[str, SliceItem] = {}
        self.slice_scale = 1.0

        # 画板信息
        self.artboard_name: str = "Unknown"
        self.artboard_frame: Dict = {}
        self.artboards: Dict[str, Dict] = {}  # 画板ID -> 画板数据
        self.design_id = None  # 设计稿唯一标识

    def _generate_design_id(self, artboard_name: str) -> str:
        """生成设计稿唯一标识（Figma格式）"""
        import hashlib
        from datetime import datetime

        # 优先从原始 URL 提取（下载场景下 json_path 是临时文件路径）
        source_path = self.original_url or self.json_path
        if source_path:
            if source_path.startswith('http'):
                url_path = source_path.split('/')[-1]
                design_id = url_path.replace('.json', '').replace('.gzip', '')
                if len(design_id) > 30:
                    design_id = design_id[:30]
                return sanitize_filename(design_id)
            else:
                file_name = Path(source_path).stem
                return sanitize_filename(file_name)

        timestamp = datetime.now().strftime('%H%M%S')
        hash_input = f"{artboard_name}_{timestamp}"
        short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:6]
        return sanitize_filename(f"{artboard_name}_{short_hash}")

    def load_json(self) -> bool:
        """加载 JSON 数据"""
        try:
            if self._json_data:
                self.data = self._json_data
                return True

            if not self.json_path:
                print("未提供 JSON 数据或文件路径")
                return False

            with open(self.json_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            return True
        except Exception as e:
            print(f"加载 JSON 失败: {e}")
            return False

    def parse(self) -> bool:
        """解析 Figma JSON 数据"""
        if not self.load_json():
            return False

        meta = self.data.get('meta', {})
        try:
            self.slice_scale = float(meta.get('sliceScale', 1.0) or 1.0)
        except (TypeError, ValueError):
            self.slice_scale = 1.0

        # 获取画板信息
        artboard = self.data.get('artboard', {})
        self.artboard_name = artboard.get('name', 'Unknown')
        self.artboard_frame = artboard.get('frame', {})

        # 生成设计稿唯一标识
        self.design_id = self._generate_design_id(self.artboard_name)

        # 输出目录：<output_dir>/<design_id>/
        self.output_dir = self.output_dir / sanitize_filename(self.design_id)

        print(f"Figma JSON 解析: 画板 '{self.artboard_name}'")
        print(f"尺寸: {self.artboard_frame.get('width', 0)}x{self.artboard_frame.get('height', 0)}")
        print(f"sliceScale: {self.slice_scale}")

        # 提取切图（从 assets 和图层）
        self._extract_figma_slices()

        # 构建组件树
        # 顶层图层的 parent_frame 为 {0, 0}，表示相对于画板内部原点
        layers = artboard.get('layers', [])
        tree = self._build_figma_tree(layers, None, {'left': 0, 'top': 0})
        if tree:
            # 顶层节点可能是多个，合并为一个虚拟根节点
            if isinstance(tree, list) and len(tree) > 0:
                root = ComponentNode(
                    type="Artboard",
                    name=self.artboard_name,
                    layerId=artboard.get('id', ''),
                    parentId=None,
                    style=self._extract_figma_box_style(artboard),
                    position={
                        "x": 0,  # 画板相对于自身是 (0, 0)
                        "y": 0,
                        "width": self.artboard_frame.get('width', 0),
                        "height": self.artboard_frame.get('height', 0),
                        "absoluteX": self.artboard_frame.get('left', 0),  # 画板在设计稿中的绝对位置
                        "absoluteY": self.artboard_frame.get('top', 0)
                    },
                    children=tree
                )
            else:
                root = tree
            self.annotations[self.artboard_name] = root

        return True

    def _build_figma_tree(self, layers: List[Dict], parent_id: Optional[str], parent_frame: Dict = None) -> List[ComponentNode]:
        """构建 Figma 图层树

        Args:
            layers: 图层列表
            parent_id: 父图层ID
            parent_frame: 父图层的 frame 信息，用于计算相对位置
        """
        nodes = []

        if parent_frame is None:
            parent_frame = {'left': 0, 'top': 0}

        for layer in layers:
            layer_id = layer.get('id', '')
            frame = layer.get('frame', {})

            # 计算相对于父容器的位置
            abs_x = frame.get('left', 0)
            abs_y = frame.get('top', 0)
            rel_x = abs_x - parent_frame.get('left', 0)
            rel_y = abs_y - parent_frame.get('top', 0)

            node = ComponentNode(
                type=self._get_figma_layer_type(layer),
                name=layer.get('name', 'Unknown'),
                layerId=layer_id,
                parentId=parent_id,
                style=self._extract_figma_box_style(layer),
                position={
                    "x": rel_x,  # 相对于父容器的位置
                    "y": rel_y,
                    "width": frame.get('width', 0),
                    "height": frame.get('height', 0),
                    "absoluteX": abs_x,  # 保留绝对坐标供参考
                    "absoluteY": abs_y
                }
            )

            # 文本图层
            if layer.get('text'):
                node.text = self._extract_figma_text_style(layer)

            # 检查切图
            slice_info = self._get_figma_slice_for_layer(layer)
            if slice_info:
                node.slice = slice_info

            # 递归处理子图层，传递当前 frame 作为父级参考
            child_layers = layer.get('layers', [])
            if child_layers:
                child_nodes = self._build_figma_tree(child_layers, layer_id, frame)
                node.children = child_nodes

            nodes.append(node)

        return nodes

    def _get_figma_layer_type(self, layer: Dict) -> str:
        """获取 Figma 图层类型"""
        layer_type = layer.get('type', '')

        type_map = {
            'shapeLayer': 'Rectangle',
            'textLayer': 'Text',
            'bitmapLayer': 'Image',
            'groupLayer': 'Group',
            'artboard': 'Artboard',
        }

        return type_map.get(layer_type, layer_type or 'Unknown')

    def _extract_figma_box_style(self, layer: Dict) -> BoxStyle:
        """提取 Figma 图层样式"""
        frame = layer.get('frame', {})
        style = BoxStyle(
            width=frame.get('width', 0),
            height=frame.get('height', 0),
            opacity=layer.get('opacity', 1.0)
        )

        # 从 style 对象提取
        layer_style = layer.get('style', {})

        # 填充（fills）
        fills = layer_style.get('fills', [])
        if fills:
            for fill in fills:
                if fill.get('isEnabled', True):
                    fill_type = fill.get('type', '')

                    if fill_type == 'color':
                        color = fill.get('color', {})
                        style.backgroundColor = parse_color(color)

        # 圆角 - 优先从 paths 中读取，再从 layer.radius 读取
        # Figma JSON 中圆角信息存储在 paths[0].radius，layer.radius 可能是默认值(0)
        radius_info = {}
        paths = layer.get('paths', [])
        if paths and isinstance(paths, list) and len(paths) > 0:
            path_radius = paths[0].get('radius', {})
            if path_radius:
                radius_info = path_radius

        # 如果 paths 中没有圆角信息或都是0，尝试读取 layer.radius
        layer_radius = layer.get('radius', {})
        if not radius_info or all(v == 0 for v in radius_info.values() if isinstance(v, (int, float))):
            if layer_radius:
                radius_info = layer_radius

        if radius_info:
            style.borderTopLeftRadius = round_metric(radius_info.get('topLeft', 0) or radius_info.get('top_left', 0) or 0)
            style.borderTopRightRadius = round_metric(radius_info.get('topRight', 0) or radius_info.get('top_right', 0) or 0)
            style.borderBottomLeftRadius = round_metric(radius_info.get('bottomLeft', 0) or radius_info.get('bottom_left', 0) or 0)
            style.borderBottomRightRadius = round_metric(radius_info.get('bottomRight', 0) or radius_info.get('bottom_right', 0) or 0)
            # 计算统一圆角（如果四个角相同）
            if (style.borderTopLeftRadius == style.borderTopRightRadius ==
                style.borderBottomLeftRadius == style.borderBottomRightRadius):
                style.borderRadius = style.borderTopLeftRadius

        # 边框
        borders = layer_style.get('borders', [])
        if borders:
            for border in borders:
                if border.get('isEnabled', True):
                    style.borderWidth = round_metric(border.get('width', 0))
                    style.borderColor = parse_color(border.get('color'))

        # 阴影
        shadows = layer_style.get('shadows', [])
        if shadows:
            for shadow in shadows:
                if shadow.get('isEnabled', True):
                    style.shadow = {
                        "type": shadow.get('type', 'outer'),
                        "offsetX": 0,
                        "offsetY": 0,
                        "blur": 0,
                        "color": parse_color(shadow.get('color'))
                    }

        return style

    def _extract_figma_text_style(self, layer: Dict) -> TextStyle:
        """提取 Figma 文本样式"""
        text_data = layer.get('text', {})
        text = TextStyle()

        # 文本内容
        text.content = text_data.get('value', '')

        # 从 style 对象提取字体信息
        text_style = text_data.get('style', {})
        font = text_style.get('font', {})

        if font:
            text.fontSize = round_metric(font.get('size', 0))
            text.fontWeight = int(font.get('fontWeight', font.get('weight', 400)))
            text.fontFamily = font.get('name', '')
            text.textAlign = font.get('align', 'left')
            text.lineHeight = round_metric(font.get('lineHeight', {}).get('value', 0) or font.get('lineSpacing', 0))
            text.letterSpacing = round_metric(font.get('letterSpacing', {}).get('value', 0))

        # 颜色
        color_data = text_style.get('color', {})
        if color_data:
            text.color = parse_color(color_data)

        return text

    def _extract_figma_slices(self):
        """提取 Figma 切图"""
        # 从 assets 提取切图 URL
        assets = self.data.get('assets', [])
        asset_urls = set(assets)

        # 遍历图层，查找有 image 信息的图层
        artboard = self.data.get('artboard', {})
        layers = artboard.get('layers', [])

        def process_layer(layer: Dict, path: str = ""):
            layer_id = layer.get('id', '')
            layer_name = layer.get('name', 'Unknown')
            current_path = f"{path}/{layer_name}" if path else layer_name

            # 检查是否有 image 信息
            image_info = layer.get('image', {})
            if image_info:
                download_url = image_info.get('imageUrl', '')
                svg_url = image_info.get('svgUrl', '')

                if download_url or svg_url:
                    self._add_figma_slice(layer, download_url, svg_url, current_path)

            # 检查 hasExportImage 标记
            if layer.get('hasExportImage') and not image_info:
                # 尝试从 assets 中匹配
                # Figma 的 assets 是 URL 列表，需要根据图层名推断
                pass

            # 递归处理子图层
            for child in layer.get('layers', []):
                process_layer(child, current_path)

        for layer in layers:
            process_layer(layer)

        print(f"提取切图: {len(self.slices)} 个")

        # 去重
        seen_urls = set()
        unique_slices = []
        for s in self.slices:
            if s.download_url not in seen_urls:
                seen_urls.add(s.download_url)
                unique_slices.append(s)
        if len(unique_slices) < len(self.slices):
            print(f"切图去重: 移除 {len(self.slices) - len(unique_slices)} 个重复项")
        self.slices = unique_slices

    def _add_figma_slice(self, layer: Dict, download_url: str, svg_url: str, layer_path: str):
        """添加 Figma 切图项"""
        layer_name = layer.get('name', 'unknown')
        frame = layer.get('frame', {})
        width = int(round(frame.get('width', 0) or 0))
        height = int(round(frame.get('height', 0) or 0))

        # 确定格式
        format_type = 'png'
        if svg_url and not download_url:
            download_url = svg_url
            format_type = 'svg'

        # 生成切图名称
        context_info = {'layer_path': layer_path}
        slice_name = generate_slice_name(
            layer_name,
            context_info=context_info,
            layer_path=layer_path
        )

        # 确定目录
        name_lower = slice_name.lower()
        if name_lower.startswith('ic_'):
            asset_subdir = "icons"
        elif name_lower.startswith('bg_'):
            asset_subdir = "backgrounds"
        elif name_lower.startswith('btn_'):
            asset_subdir = "buttons"
        else:
            asset_subdir = "images"

        local_path = f"assets/{asset_subdir}/{slice_name}"
        drawable_name = slice_name.rsplit('.', 1)[0]

        slice_item = SliceItem(
            name=slice_name,
            format=format_type,
            density="xxhdpi",
            size=f"{width}x{height}",
            actual_size=f"{width}x{height}",
            source_layer=layer_name,
            node_id=layer.get('id', ''),
            node_x=self._to_dp(frame.get('left', 0)),
            node_y=self._to_dp(frame.get('top', 0)),
            ancestor_path=layer_path,
            download_url=download_url,
            svg_url=svg_url,
            local_path=local_path,
            drawable_name=drawable_name,
            status="available",
            scale=self.slice_scale
        )

        self.slices.append(slice_item)
        self.slice_map[layer.get('id', '')] = slice_item

    def _get_figma_slice_for_layer(self, layer: Dict) -> Optional[SliceInfo]:
        """获取图层对应的切图信息"""
        layer_id = layer.get('id', '')
        if layer_id in self.slice_map:
            slice_item = self.slice_map[layer_id]
            return SliceInfo(
                name=slice_item.name,
                local_path=slice_item.local_path,
                drawable_name=slice_item.drawable_name,
                size=slice_item.size,
                status=slice_item.status
            )
        return None

    def save_outputs(self):
        """保存输出产物"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 保存 annotations
        annotations_file = self.output_dir / "annotations.json"
        annotations_data = {}
        for name, tree in self.annotations.items():
            annotations_data[name] = self._node_to_dict(tree)
        with open(annotations_file, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=2)
        print(f"结构化标注已保存: {annotations_file}")

        save_slices_file(self.output_dir, self.slices, self.slice_scale)
        save_issues_file(self.output_dir, self.issues)

        # 创建切图目录
        assets_dir = self.output_dir / "assets"
        (assets_dir / "icons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
        (assets_dir / "buttons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "images").mkdir(parents=True, exist_ok=True)
        print(f"切图目录已创建: {assets_dir}")

    def _node_to_dict(self, node: ComponentNode) -> Dict:
        """将节点转换为字典"""
        position = dict(node.position)
        for key in ("x", "y", "width", "height", "absoluteX", "absoluteY", "absX", "absY"):
            if key in position:
                position[key] = self._to_dp(position[key])

        style_dict = asdict(node.style)
        for key in ("width", "height", "borderRadius", "borderTopLeftRadius", "borderTopRightRadius",
                    "borderBottomLeftRadius", "borderBottomRightRadius", "borderWidth"):
            if key in style_dict:
                style_dict[key] = self._to_dp(style_dict[key])
        if style_dict.get("shadow"):
            style_dict["shadow"] = self._scaled_shadow(style_dict["shadow"])

        result = {
            "type": node.type,
            "name": node.name,
            "layerId": node.layerId,
            "position": position,
            "style": style_dict,
        }
        if node.text:
            text_dict = asdict(node.text)
            for key in ("fontSize", "lineHeight", "letterSpacing"):
                text_dict[key] = self._to_dp(text_dict.get(key, 0))
            for segment in text_dict.get("segments", []):
                for key in ("fontSize", "lineHeight"):
                    segment[key] = self._to_dp(segment.get(key, 0))
            result["text"] = text_dict
        if node.slice:
            result["slice"] = asdict(node.slice)
        if node.children:
            result["children"] = [self._node_to_dict(c) for c in node.children]
        return result

    def _get_primary_artboard_width(self) -> float:
        """获取主画板宽度（用于推断密度系数）。

        优先从 self.artboards 读取（Sketch 流程），
        Figma 流程下 artboards 为空则回退到 self.artboard_frame。
        """
        if self.artboards:
            first = list(self.artboards.values())[0]
            return float(first.get('width', 0))
        # Figma 流程：画板数据存在 self.artboard_frame 中
        if hasattr(self, 'artboard_frame') and self.artboard_frame:
            w = self.artboard_frame.get('width', 0)
            if w:
                return float(w)
        return 0

    def _dp_scale(self) -> float:
        """从画板宽度推断密度系数，替代 slice_scale。

        画板 ≤ 430px → 1x 设计，坐标值本身就是 dp，无需换算。
        画板 ≥ 1000px → 尝试用标准密度还原（1080÷3=360dp, 1440÷4=360dp等）。
        """
        w = self._get_primary_artboard_width()
        if w <= 0:
            return 1.0
        if w <= 430:
            return 1.0
        for factor in (4.0, 3.0, 2.0, 1.5):
            dp_w = w / factor
            if 320 <= dp_w <= 430 and abs(dp_w - round(dp_w)) < 0.1:
                return factor
        return 1.0

    def _to_dp(self, value: Any) -> float:
        """把原始 px 标注转换为 Android dp，保留两位小数。"""
        try:
            numeric = float(value or 0)
        except (TypeError, ValueError):
            return 0
        scale = self._dp_scale()
        converted = numeric / scale if scale > 1 else numeric
        return round(converted, 2)

    def _scaled_shadow(self, shadow: Dict) -> Dict:
        """阴影几何参数按 dp 输出，颜色和类型保持原样。"""
        scaled = dict(shadow)
        for key in ("offsetX", "offsetY", "blur", "spread"):
            if key in scaled:
                scaled[key] = self._to_dp(scaled[key])
        return scaled

    def _infer_visual_role(self, node: ComponentNode) -> Dict:
        """为 XML/Compose 生成提供轻量语义提示，减少后续凭名字猜测。"""
        name = (node.name or "").lower()
        width = node.position.get("width_dp", 0)
        height = node.position.get("height_dp", 0)
        role = "container" if node.children else "shape"
        android_view = "ConstraintLayout" if node.children else "View"
        render_mode = "compose_children"

        if node.text:
            role = "text"
            android_view = "TextView"
            render_mode = "text"
        elif node.slice:
            if "tab" in name:
                role = "tab_bar"
            elif "btn" in name or "button" in name or "按钮" in node.name or "点击" in node.name:
                role = "button_asset"
            elif width <= 40 and height <= 40:
                role = "icon"
            elif width >= 160 or height >= 120:
                role = "image_or_background"
            else:
                role = "image"
            android_view = "ImageView"
            render_mode = "slice_only"
        elif node.type in ("Rectangle", "Oval"):
            role = "background" if width >= 120 or height >= 80 else "shape"
            android_view = "View"
            render_mode = "shape"

        hint = {
            "role": role,
            "androidView": android_view,
            "renderMode": render_mode,
        }
        if node.slice:
            hint["preferSlice"] = True
        return hint

    def _node_to_dict_compact(self, node: ComponentNode) -> Dict:
        """紧凑版节点转换（Figma格式）"""
        result = {
            "id": node.layerId,
            "name": node.name,
            "type": node.type,
        }

        # position：相对坐标 + 绝对坐标（供跨层级对齐检测）
        pos = node.position
        result["x"] = self._to_dp(pos.get("x", 0))
        result["y"] = self._to_dp(pos.get("y", 0))
        result["width"] = self._to_dp(pos.get("width", 0))
        result["height"] = self._to_dp(pos.get("height", 0))
        if "absoluteX" in pos:
            result["absX"] = self._to_dp(pos.get("absoluteX", 0))
        if "absoluteY" in pos:
            result["absY"] = self._to_dp(pos.get("absoluteY", 0))

        # style：只存非默认值
        style_compact = {}
        style = node.style

        # 合并 opacity 到颜色（优先合并，避免 AI 手动计算）
        style_merged_opacity = False
        if style.opacity < 1.0:
            if style.backgroundColor and style.backgroundColor != "#00000000":
                merged_bg = apply_opacity_to_color(style.backgroundColor, style.opacity)
                style_compact["backgroundColor"] = merged_bg
                style_merged_opacity = True
            if style.borderColor:
                merged_border = apply_opacity_to_color(style.borderColor, style.opacity)
                style_compact["borderColor"] = merged_border
                style_merged_opacity = True

        # backgroundColor：如果上面没有合并 opacity，且颜色非透明，直接输出
        if style.backgroundColor and style.backgroundColor != "#00000000" and not style_merged_opacity:
            style_compact["backgroundColor"] = style.backgroundColor

        if style.borderRadius > 0:
            style_compact["borderRadius"] = self._to_dp(style.borderRadius)
        elif (style.borderTopLeftRadius > 0 or style.borderTopRightRadius > 0 or
              style.borderBottomLeftRadius > 0 or style.borderBottomRightRadius > 0):
            radii = {}
            if style.borderTopLeftRadius > 0:
                radii["topLeft"] = self._to_dp(style.borderTopLeftRadius)
            if style.borderTopRightRadius > 0:
                radii["topRight"] = self._to_dp(style.borderTopRightRadius)
            if style.borderBottomLeftRadius > 0:
                radii["bottomLeft"] = self._to_dp(style.borderBottomLeftRadius)
            if style.borderBottomRightRadius > 0:
                radii["bottomRight"] = self._to_dp(style.borderBottomRightRadius)
            if radii:
                style_compact["borderRadii"] = radii

        if style.borderWidth > 0:
            style_compact["borderWidth"] = self._to_dp(style.borderWidth)
            # borderColor 已在 opacity 合并阶段处理

        # 仅当 opacity 没有合并到任何颜色时才保留独立字段
        if style.opacity < 1.0 and not style_merged_opacity:
            style_compact["opacity"] = round(style.opacity, 2)

        if style.shadow:
            style_compact["shadow"] = self._scaled_shadow(style.shadow)

        if style_compact:
            result["style"] = style_compact

        if node.slice:
            result["slice"] = {"drawable": node.slice.drawable_name, "size": node.slice.size}

        if node.text:
            text_compact = {"content": node.text.content, "fontSize": self._to_dp(node.text.fontSize)}
            if has_meaningful_value(node.text.lineHeight):
                text_compact["lineHeight"] = self._to_dp(node.text.lineHeight)
            if has_meaningful_value(node.text.letterSpacing):
                text_compact["letterSpacing"] = self._to_dp(node.text.letterSpacing)
            if node.text.fontFamily:
                text_compact["fontFamily"] = node.text.fontFamily
            if node.text.color and node.text.color != "#000000":
                text_compact["color"] = node.text.color
            if node.text.fontWeight and node.text.fontWeight != 400:
                text_compact["fontWeight"] = node.text.fontWeight
            if node.text.textAlign and node.text.textAlign != "left":
                text_compact["textAlign"] = node.text.textAlign

            # 富文本分段样式（当有多个分段且样式不同时）
            if node.text.segments and len(node.text.segments) > 1:
                has_color_diff = any(s.color != node.text.segments[0].color for s in node.text.segments)
                has_weight_diff = any(s.fontWeight != node.text.segments[0].fontWeight for s in node.text.segments)
                has_size_diff = any(abs(s.fontSize - node.text.segments[0].fontSize) > 1e-6 for s in node.text.segments)
                has_line_height_diff = any(abs(s.lineHeight - node.text.segments[0].lineHeight) > 1e-6 for s in node.text.segments)
                has_font_family_diff = any(s.fontFamily != node.text.segments[0].fontFamily for s in node.text.segments)
                if has_color_diff or has_weight_diff or has_size_diff or has_line_height_diff or has_font_family_diff:
                    segments_compact = []
                    for seg in node.text.segments:
                        seg_data = {"content": seg.content, "start": seg.start, "end": seg.end}
                        if seg.color and seg.color != "#000000":
                            seg_data["color"] = seg.color
                        if seg.fontWeight and seg.fontWeight != 400:
                            seg_data["fontWeight"] = seg.fontWeight
                        if has_meaningful_value(seg.fontSize):
                            seg_data["fontSize"] = self._to_dp(seg.fontSize)
                        if seg.fontFamily:
                            seg_data["fontFamily"] = seg.fontFamily
                        if has_meaningful_value(seg.lineHeight):
                            seg_data["lineHeight"] = self._to_dp(seg.lineHeight)
                        segments_compact.append(seg_data)
                    text_compact["segments"] = segments_compact

            result["text"] = text_compact

        if node.children:
            result["children"] = [c.layerId for c in node.children]

        # renderHint：为后续 XML 阶段提供轻量语义提示
        result["renderHint"] = self._infer_visual_role(node)

        return result

    def _enrich_tree(self):
        """后处理：补全 siblingGap、parentMargins、orientation，并进行布局语义分析"""
        for name, tree in self.annotations.items():
            self._enrich_node(tree, None)

    def _enrich_node(self, node: ComponentNode, parent_node: Optional[ComponentNode]):
        """递归补全单个节点的布局信息（Figma版本，从零计算）

        Args:
            node: 当前节点
            parent_node: 父节点（用于计算 parentRelative 坐标）
        """
        children = node.children

        # 计算全局绝对坐标（dp 单位）
        dp_scale = self._dp_scale()
        abs_x = self._to_dp(node.position.get("absoluteX", node.position.get("x", 0)))
        abs_y = self._to_dp(node.position.get("absoluteY", node.position.get("y", 0)))
        node.position["_absX"] = abs_x
        node.position["_absY"] = abs_y

        if not children:
            return

        # 父容器尺寸（dp）
        pw = self._to_dp(node.position.get("width", 0))
        ph = self._to_dp(node.position.get("height", 0))

        # 分析子元素排列方向
        orientation = self._analyze_children_orientation(children)
        if orientation:
            node.orientation = orientation

        # 遍历子元素，计算 sibling_gap 和 parentMargins
        prev_child = None
        for i, child in enumerate(children):
            # 子元素坐标（dp）
            child_abs_x = self._to_dp(child.position.get("absoluteX", child.position.get("x", 0)))
            child_abs_y = self._to_dp(child.position.get("absoluteY", child.position.get("y", 0)))
            cw = self._to_dp(child.position.get("width", 0))
            ch = self._to_dp(child.position.get("height", 0))

            # 相对于父容器的坐标
            cx = round(child_abs_x - abs_x, 2)
            cy = round(child_abs_y - abs_y, 2)
            child.position["parentRelative"] = {"x": cx, "y": cy}

            # sibling_gap：与上一个兄弟元素的间距
            sibling_gap = {}
            if prev_child:
                prev_abs_y = prev_child.position.get("_absY", 0)
                prev_abs_x = prev_child.position.get("_absX", 0)
                prev_h = self._to_dp(prev_child.position.get("height", 0))
                prev_w = self._to_dp(prev_child.position.get("width", 0))

                # 垂直间距（下方元素）
                if child_abs_y > prev_abs_y + prev_h:
                    gap = round(child_abs_y - (prev_abs_y + prev_h), 2)
                    sibling_gap["above"] = gap
                    # 补全上一个兄弟的 below
                    if "below" not in prev_child.sibling_gap:
                        prev_child.sibling_gap["below"] = gap

                # 水平间距（右侧元素）
                if child_abs_x > prev_abs_x + prev_w:
                    gap = round(child_abs_x - (prev_abs_x + prev_w), 2)
                    sibling_gap["left"] = gap
                    # 补全上一个兄弟的 right
                    if "right" not in prev_child.sibling_gap:
                        prev_child.sibling_gap["right"] = gap

            if sibling_gap:
                child.sibling_gap = sibling_gap

            # parentMargins：首/尾子元素的父容器边距
            margins = {}
            if i == 0 and cy > 0:
                margins["top"] = round(cy, 2)
            if i == len(children) - 1 and ph > 0:
                bm = ph - (cy + ch)
                if bm > 0:
                    margins["bottom"] = round(bm, 2)
            if cx > 0:
                margins["start"] = round(cx, 2)
            if pw > 0:
                em = pw - (cx + cw)
                if em > 0:
                    margins["end"] = round(em, 2)

            if margins:
                child.position["parentMargins"] = margins

            prev_child = child
            self._enrich_node(child, node)

    def _analyze_children_orientation(self, children: List[ComponentNode]) -> str:
        """分析子元素的排列方向（Figma版本，从节点列表计算）

        Returns:
            "vertical" - 纵向排列（子元素 Y 坐标递增）
            "horizontal" - 横向排列（子元素 X 坐标递增）
            "" - 无法判断
        """
        if len(children) < 2:
            return ""

        # 收集子元素位置（dp）
        positions = []
        for child in children:
            abs_x = self._to_dp(child.position.get("absoluteX", child.position.get("x", 0)))
            abs_y = self._to_dp(child.position.get("absoluteY", child.position.get("y", 0)))
            width = self._to_dp(child.position.get("width", 0))
            height = self._to_dp(child.position.get("height", 0))
            positions.append({
                'x': abs_x,
                'y': abs_y,
                'width': width,
                'height': height
            })

        # 按 Y 坐标排序（过滤掉可能的大背景元素）
        widths = [p['width'] for p in positions]
        heights = [p['height'] for p in positions]
        median_width = sorted(widths)[len(widths)//2] if widths else 0
        median_height = sorted(heights)[len(heights)//2] if heights else 0

        # 过滤掉明显是背景的元素（尺寸远大于中位数）
        filtered = [
            p for p in positions
            if p['width'] <= median_width * 2 and p['height'] <= median_height * 2
        ]

        if len(filtered) < 2:
            return ""

        # 按 Y 坐标排序后判断递增
        sorted_by_y = sorted(filtered, key=lambda p: p['y'])

        y_increasing = 0
        x_increasing = 0
        for i in range(1, len(sorted_by_y)):
            prev = sorted_by_y[i-1]
            curr = sorted_by_y[i]
            if curr['y'] > prev['y']:
                y_increasing += 1
            if curr['x'] > prev['x']:
                x_increasing += 1

        total = len(sorted_by_y) - 1
        y_ratio = y_increasing / total if total > 0 else 0
        x_ratio = x_increasing / total if total > 0 else 0

        if y_ratio >= 0.6 and y_ratio > x_ratio:
            return "vertical"
        elif x_ratio >= 0.6 and x_ratio > y_ratio:
            return "horizontal"
        return ""

    def save_outputs_compact(self):
        """紧凑版输出（Figma格式）"""
        # 先补全布局信息（siblingGap、parentMargins、orientation、renderHint）
        self._enrich_tree()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        dp_scale = self._dp_scale()
        scale_info = {
            "sliceScale": self.slice_scale,
            "artboardScale": 1.0,
            "dpScale": dp_scale,
            "conversion_note": "数值已为 dp/sp 单位，直接使用。dpScale 是切图导出倍率，不是坐标换算系数。",
        }

        index = {}
        nodes_compact = {}

        for name, tree in self.annotations.items():
            self._build_flat_index(tree, index, nodes_compact, level=0, parent_id=None)

        annotations_data = {
            "_unit": "dp",  # 所有坐标/尺寸/圆角/字号字段的单位标记
            "scale": scale_info,
            "artboard": {
                "name": self.artboard_name,
                "root": tree.layerId if self.annotations else ""
            },
            "index": index,
            "nodes": nodes_compact,
            "layoutAnalysis": {},
        }

        annotations_file = self.output_dir / "annotations.json"
        with open(annotations_file, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=1)
        print(f"结构化标注已保存（紧凑格式）: {annotations_file}")

        save_slices_file(self.output_dir, self.slices, self.slice_scale)
        save_issues_file(self.output_dir, self.issues)

        assets_dir = self.output_dir / "assets"
        (assets_dir / "icons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
        (assets_dir / "buttons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "images").mkdir(parents=True, exist_ok=True)
        print(f"切图目录已创建: {assets_dir}")

    def _build_flat_index(self, node: ComponentNode, index: Dict, nodes: Dict,
                           level: int, parent_id: Optional[str]):
        """递归构建扁平索引（Figma格式）"""
        entry = {
            "name": node.name,
            "type": node.type,
            "level": level,
            "parent": parent_id,
            "children": [c.layerId for c in node.children] if node.children else [],
            "has_slice": bool(node.slice),
            "has_text": bool(node.text),
        }
        # 快速布局提示：orientation 和 parentMargins
        if node.orientation:
            entry["orientation"] = node.orientation
        pm = node.position.get("parentMargins")
        if pm:
            entry["parentMargins"] = pm
        index[node.layerId] = entry

        nodes[node.layerId] = self._node_to_dict_compact(node)

        for child in node.children:
            self._build_flat_index(child, index, nodes, level + 1, node.layerId)

    def download_slices(self, max_workers: int = 5):
        """下载切图资源"""
        download_slice_assets(self, max_workers=max_workers)

    def download_screenshot(self, screenshot_url: str) -> Optional[str]:
        """下载页面截图"""
        return save_screenshot_resource(self.output_dir, screenshot_url)

    def validate_structure(self) -> List[Dict]:
        """验证结构化标注"""
        issues = []
        for artboard_name, tree in self.annotations.items():
            self._validate_node(tree, artboard_name, issues)
        return issues

    def _validate_node(self, node: ComponentNode, screen_name: str, issues: List[Dict]):
        """验证单个节点"""
        if node.type == 'Text' and node.text:
            if not node.text.content:
                issues.append({
                    "type": "标注缺失",
                    "screen": screen_name,
                    "layer": node.name,
                    "description": "文本内容为空",
                    "workaround": None
                })

        if node.slice and node.slice.status == "missing":
            issues.append({
                "type": "切图缺失",
                "screen": screen_name,
                "layer": node.name,
                "description": f"切图 {node.slice.name} 下载失败",
                "workaround": "使用占位图替代"
            })

        for child in node.children:
            self._validate_node(child, screen_name, issues)


# ==================== Sketch JSON 解析器 ====================

class LanhuSketchParser:
    """蓝湖Sketch JSON解析器"""

    def __init__(self, json_path: str = None, output_dir: str = "./output", json_data: Dict = None,
                 scale: float = 3.0, original_url: str = None):
        """
        初始化解析器

        Args:
            json_path: JSON文件路径（可选）
            output_dir: 输出目录
            json_data: 直接传入的JSON数据（可选，优先级高于json_path）
            scale: 设计稿密度比例 (默认3.0 = xxhdpi，用于将px转为dp/sp)
            original_url: 原始 URL（下载场景下 json_path 会变成临时文件路径）
        """
        self.json_path = json_path
        self.original_url = original_url  # 保存原始 URL
        self.output_dir = Path(output_dir)
        self._json_data = json_data  # 直接传入的JSON数据
        self.data: Dict = {}
        self.artboards: Dict[str, Dict] = {}  # 画板ID -> 画板数据
        self.layers: Dict[str, Dict] = {}  # 图层ID -> 图层数据
        self.layer_tree: Dict[str, List[str]] = {}  # 父ID -> 子ID列表
        self.slice_map: Dict[str, SliceItem] = {}  # 图层ID -> 切图项
        self.scale = scale  # 设计稿密度比例 (xxhdpi=3)
        self.slice_scale = 1.0  # 蓝湖切图缩放因子 (从JSON中读取)
        self.design_id = None  # 设计稿唯一标识（从URL提取或生成hash）

        # 输出结果
        self.annotations: Dict[str, ComponentNode] = {}  # 画板名 -> 结构树
        self.slices: List[SliceItem] = []
        self.issues: List[IssueItem] = []

    def _generate_design_id(self, page_name: str) -> str:
        """
        生成设计稿唯一标识

        策略：
        1. URL 模式：提取 URL 中的 image_id 或文件名部分
        2. 本地文件模式：使用文件名（不含扩展名）
        3. 直接 JSON 模式：使用画板名 + 短 hash
        """
        import hashlib
        from datetime import datetime

        # 优先从原始 URL 提取（下载场景下 json_path 是临时文件路径）
        source_path = self.original_url or self.json_path
        if source_path:
            # URL 模式
            if source_path.startswith('http'):
                # 尝试提取蓝湖 URL 中的 ID 部分
                # 格式1: https://alipic.lanhuapp.com/FigmaJSON/xxx.json
                # 格式2: https://alipic.lanhuapp.com/SketchJSON/xxx.json
                # 格式3: https://xxx.lanhuapp.com/xxx/<hash>.json
                url_path = source_path.split('/')[-1]
                # 移除 .json 扩展名
                design_id = url_path.replace('.json', '').replace('.gzip', '')

                # 如果 ID 太长（超过30字符），取前30字符
                if len(design_id) > 30:
                    design_id = design_id[:30]

                return sanitize_filename(design_id)

            # 本地文件模式
            else:
                # 使用文件名（不含扩展名）
                file_name = Path(source_path).stem
                return sanitize_filename(file_name)

        # 直接 JSON 数据模式：使用画板名 + 时间戳短 hash
        timestamp = datetime.now().strftime('%H%M%S')
        hash_input = f"{page_name}_{timestamp}"
        short_hash = hashlib.md5(hash_input.encode()).hexdigest()[:6]
        return sanitize_filename(f"{page_name}_{short_hash}")

    def load_json(self) -> bool:
        """加载JSON数据"""
        try:
            # 优先使用直接传入的JSON数据
            if self._json_data:
                self.data = self._json_data
                return True

            # 否则从文件加载
            if not self.json_path:
                print("未提供JSON数据或文件路径")
                return False

            with open(self.json_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            return True
        except Exception as e:
            print(f"加载JSON失败: {e}")
            return False

    def parse(self) -> bool:
        """解析JSON数据"""
        if not self.load_json():
            return False

        # 读取 sliceScale (蓝湖切图缩放因子)
        self.slice_scale = self.data.get('sliceScale', 1.0)
        if self.slice_scale != 1.0:
            print(f"检测到 sliceScale: {self.slice_scale} (切图将自动缩放)")

        # 获取页面名
        page_name = self.data.get('pageName', 'Unknown')

        # 生成设计稿唯一标识
        self.design_id = self._generate_design_id(page_name)

        # 输出目录：<output_dir>/<design_id>/
        self.output_dir = self.output_dir / sanitize_filename(self.design_id)

        # 解析所有图层
        info_list = self.data.get('info', [])
        for layer in info_list:
            layer_id = layer.get('id')
            if layer_id:
                self.layers[layer_id] = layer

                # 记录父子关系
                parent_id = layer.get('parentID')
                if parent_id:
                    if parent_id not in self.layer_tree:
                        self.layer_tree[parent_id] = []
                    self.layer_tree[parent_id].append(layer_id)

                # 识别画板
                if layer.get('ddsType') == 'artboard-group':
                    self.artboards[layer_id] = layer

        print(f"解析完成: {len(self.artboards)} 个画板, {len(self.layers)} 个图层")

        # 先提取切图，供后续构建树时关联
        self._extract_slices()

        # 构建每个画板的结构树
        for artboard_id, artboard in self.artboards.items():
            artboard_name = artboard.get('name', 'Unknown')
            tree = self._build_component_tree(artboard_id)
            self.annotations[artboard_name] = tree

        return True

    def _build_component_tree(self, layer_id: str, sibling_index: int = 0, sibling_count: int = 0, prev_sibling: Dict = None) -> ComponentNode:
        """构建组件树

        Args:
            layer_id: 图层ID
            sibling_index: 当前节点在兄弟节点中的索引（0-based）
            sibling_count: 兄弟节点总数
            prev_sibling: 上一个兄弟节点的信息 {y, height, x, width}
        """
        layer = self.layers.get(layer_id, {})

        # 原始 px 值
        px_x = layer.get('left', 0)
        px_y = layer.get('top', 0)
        px_width = layer.get('width', 0)
        px_height = layer.get('height', 0)

        # annotations.json 对外只暴露 dp 语义，后续 XML 不再二次换算。
        dp_scale = self._dp_scale()
        dp_x = round(px_x / dp_scale, 2) if dp_scale > 1 else px_x
        dp_y = round(px_y / dp_scale, 2) if dp_scale > 1 else px_y
        dp_width = round(px_width / dp_scale, 2) if dp_scale > 1 else px_width
        dp_height = round(px_height / dp_scale, 2) if dp_scale > 1 else px_height

        # 计算 sibling 间距（与上一个兄弟元素的间距）
        sibling_gap = {}
        if prev_sibling:
            prev_y = prev_sibling.get('y', 0)
            prev_height = prev_sibling.get('height', 0)
            prev_x = prev_sibling.get('x', 0)
            prev_width = prev_sibling.get('width', 0)

            # 垂直间距（下方元素）
            if px_y > prev_y + prev_height:
                gap_px = px_y - (prev_y + prev_height)
                gap_dp = round(gap_px / dp_scale, 2) if dp_scale > 1 else gap_px
                sibling_gap['above'] = gap_dp

            # 水平间距（右侧元素）
            if px_x > prev_x + prev_width:
                gap_px = px_x - (prev_x + prev_width)
                gap_dp = round(gap_px / dp_scale, 2) if dp_scale > 1 else gap_px
                sibling_gap['left'] = gap_dp

        node = ComponentNode(
            type=self._get_component_type(layer),
            name=layer.get('name', 'Unknown'),
            layerId=layer_id,
            parentId=layer.get('parentID'),
            style=self._extract_box_style(layer),
            position={
                # px 单位（原始值）
                "x_px": px_x,
                "y_px": px_y,
                "width_px": px_width,
                "height_px": px_height,
                # dp 单位（换算后）
                "x_dp": dp_x,
                "y_dp": dp_y,
                "width_dp": dp_width,
                "height_dp": dp_height,
            },
            sibling_gap=sibling_gap
        )

        # 提取文本样式
        if layer.get('type') == 'text':
            node.text = self._extract_text_style(layer)

        # 检查是否有关联的切图
        slice_info = self._get_slice_for_layer(layer)
        if slice_info:
            node.slice = slice_info

        # 递归构建子节点，同时分析排列方向
        child_ids = self.layer_tree.get(layer_id, [])
        child_nodes = []
        prev_child_info = None

        for idx, child_id in enumerate(child_ids):
            child_node = self._build_component_tree(
                child_id,
                sibling_index=idx,
                sibling_count=len(child_ids),
                prev_sibling=prev_child_info
            )
            child_nodes.append(child_node)

            # 记录当前子节点信息，供下一个子节点计算间距
            child_layer = self.layers.get(child_id, {})
            prev_child_info = {
                'y': child_layer.get('top', 0),
                'height': child_layer.get('height', 0),
                'x': child_layer.get('left', 0),
                'width': child_layer.get('width', 0)
            }

        node.children = child_nodes

        # 分析子元素排列方向
        if len(child_nodes) >= 2:
            node.orientation = self._analyze_children_orientation(child_ids)

        return node

    def _analyze_children_orientation(self, child_ids: List[str]) -> str:
        """分析子元素的排列方向

        Returns:
            "vertical" - 纵向排列（子元素 Y 坐标递增）
            "horizontal" - 横向排列（子元素 X 坐标递增）
            "" - 无法判断
        """
        if len(child_ids) < 2:
            return ""

        # 收集子元素位置
        positions = []
        for child_id in child_ids:
            child_layer = self.layers.get(child_id, {})
            positions.append({
                'x': child_layer.get('left', 0),
                'y': child_layer.get('top', 0),
                'width': child_layer.get('width', 0),
                'height': child_layer.get('height', 0)
            })

        # 按 Y 坐标排序（过滤掉可能的大背景元素）
        # 背景元素通常特点是：尺寸特别大（覆盖整个容器）
        # 找出容器的参考尺寸（取中位数而非最大值）
        widths = [p['width'] for p in positions]
        heights = [p['height'] for p in positions]
        median_width = sorted(widths)[len(widths)//2] if widths else 0
        median_height = sorted(heights)[len(heights)//2] if heights else 0

        # 过滤掉明显是背景的元素（尺寸远大于中位数）
        filtered_positions = [
            p for p in positions
            if p['width'] <= median_width * 2 and p['height'] <= median_height * 2
        ]

        # 如果过滤后只剩1个元素，无法判断方向
        if len(filtered_positions) < 2:
            return ""

        # 按 Y 坐标排序
        sorted_by_y = sorted(filtered_positions, key=lambda p: p['y'])

        # 计算排序后的 Y 递增情况
        y_increasing_count = 0
        x_increasing_count = 0

        for i in range(1, len(sorted_by_y)):
            prev = sorted_by_y[i-1]
            curr = sorted_by_y[i]

            # Y 递增（当前元素 Y > 上一个元素 Y）
            if curr['y'] > prev['y']:
                y_increasing_count += 1

            # X 递增（当前元素 X > 上一个元素 X）
            if curr['x'] > prev['x']:
                x_increasing_count += 1

        # 计算比例
        total_pairs = len(sorted_by_y) - 1
        y_ratio = y_increasing_count / total_pairs if total_pairs > 0 else 0
        x_ratio = x_increasing_count / total_pairs if total_pairs > 0 else 0

        # 判断排列方向（需要超过 60% 的元素符合递增规律）
        if y_ratio >= 0.6 and y_ratio > x_ratio:
            return "vertical"
        elif x_ratio >= 0.6 and x_ratio > y_ratio:
            return "horizontal"

        # 无法判断
        return ""

    def _get_component_type(self, layer: Dict) -> str:
        """获取组件类型"""
        dds_type = layer.get('ddsType', '')
        layer_type = layer.get('type', '')

        type_map = {
            'artboard-group': 'Artboard',
            'rectangle': 'Rectangle',
            'oval': 'Oval',
            'text': 'Text',
            'bitmap': 'Image',
            'slice': 'Slice',
            'shape-group': 'ShapeGroup',
            'shapePath': 'ShapePath',
            'layer-group': 'Group',
            'symbolInstance': 'Symbol',
            'triangle': 'Triangle',
        }

        if dds_type in type_map:
            return type_map[dds_type]
        if layer_type in type_map:
            return type_map[layer_type]

        return layer_type or 'Unknown'

    def _extract_box_style(self, layer: Dict) -> BoxStyle:
        """提取盒子样式"""
        style = BoxStyle(
            width=layer.get('width', 0),
            height=layer.get('height', 0),
            opacity=layer.get('opacity', 100) / 100.0
        )

        # 提取背景色
        fills = layer.get('fills', [])
        if fills:
            for fill in fills:
                if fill.get('isEnabled', True):
                    fill_type = fill.get('type', '')
                    if fill_type == 'color':
                        style.backgroundColor = parse_color(fill.get('color'))

        # 提取圆角
        if 'fixedRadius' in layer:
            style.borderRadius = round_metric(layer.get('fixedRadius', 0))
        else:
            points = layer.get('points', [])
            if points:
                indexed_radii = [round_metric(p.get('cornerRadius', 0)) for p in points]
                non_zero_radii = [radius for radius in indexed_radii if has_meaningful_value(radius)]
                if non_zero_radii:
                    if len(indexed_radii) >= 4:
                        style.borderTopLeftRadius = indexed_radii[0]
                        style.borderTopRightRadius = indexed_radii[1]
                        style.borderBottomRightRadius = indexed_radii[2]
                        style.borderBottomLeftRadius = indexed_radii[3]
                        if (style.borderTopLeftRadius == style.borderTopRightRadius ==
                            style.borderBottomLeftRadius == style.borderBottomRightRadius):
                            style.borderRadius = style.borderTopLeftRadius
                    else:
                        style.borderRadius = non_zero_radii[0]

        # 提取边框
        borders = layer.get('borders', [])
        if borders:
            for border in borders:
                if border.get('isEnabled', True):
                    style.borderWidth = round_metric(border.get('thickness', 0))
                    style.borderColor = parse_color(border.get('color'))

        # 提取阴影
        shadows = layer.get('shadows', [])
        if shadows:
            for shadow in shadows:
                if shadow.get('isEnabled', True):
                    style.shadow = {
                        "type": "inner" if shadow.get('type') == 1 else "outer",
                        "offsetX": shadow.get('offsetX', 0),
                        "offsetY": shadow.get('offsetY', 0),
                        "blur": shadow.get('blurRadius', 0),
                        "spread": shadow.get('spread', 0),
                        "color": parse_color(shadow.get('color'))
                    }

        return style

    def _extract_text_style(self, layer: Dict) -> TextStyle:
        """提取文本样式，支持富文本分段颜色和字重"""
        text = TextStyle()

        # 文本内容 — 优先从实际文本字段获取，其次 attributedString，最后 fallback 到 name
        raw_text = layer.get('text', {})
        if isinstance(raw_text, dict):
            text.content = raw_text.get('value', '') or raw_text.get('string', '')
        if not text.content:
            attr_str = layer.get('attributedString', {})
            if isinstance(attr_str, dict):
                text.content = attr_str.get('string', '')
        if not text.content:
            text.content = layer.get('stringValue', '')
        if not text.content:
            text.content = layer.get('name', '')

        font = layer.get('font', {})
        if font:
            # 字体和坐标使用同一 dp/sp 换算规则，避免 sliceScale=1 时被二次缩小。
            scale = self._dp_scale()

            def to_sp(value: Any) -> float:
                try:
                    raw = float(value or 0)
                except (TypeError, ValueError):
                    return 0.0
                return round(raw / scale, 2) if scale > 1 else round(raw, 2)

            text.fontSize = to_sp(font.get('size', 0))
            text.lineHeight = to_sp(font.get('line', 0))
            text.letterSpacing = to_sp(font.get('kerning', 0))
            text.textAlign = font.get('align', 'left')

            # 提取 fontFamily（从顶层 font 字段）
            font_family = font.get('font', '')
            if font_family:
                text.fontFamily = font_family
                text.fontWeight = parse_font_weight(font_family)

            # 从 styles 中提取分段样式（富文本颜色/字重分段）
            styles = font.get('styles', [])
            if styles:
                first_style = styles[0] if styles else {}

                # 提取第一段的颜色作为整体颜色（兼容旧逻辑）
                color_data = first_style.get('color', {})
                if color_data:
                    text.color = parse_color(color_data) or "#000000"

                # 如果第一段有 font 信息，更新 fontFamily 和 fontWeight
                first_font = first_style.get('font', '')
                if first_font:
                    text.fontFamily = first_font
                    text.fontWeight = parse_font_weight(first_font)

                # 提取所有分段样式（用于富文本还原）
                segments = []
                full_content = text.content
                for style_item in styles:
                    segment_content = style_item.get('content', '')
                    segment_font = style_item.get('font', '')
                    segment_color_data = style_item.get('color', {})
                    segment_size = style_item.get('size', font.get('size', 0))

                    # 计算分段位置
                    start_pos = full_content.find(segment_content)
                    if start_pos >= 0:
                        end_pos = start_pos + len(segment_content)
                    else:
                        # 如果找不到精确匹配，使用 location 字段
                        location = style_item.get('location', '0')
                        try:
                            start_pos = int(location)
                            end_pos = start_pos + len(segment_content)
                        except (ValueError, TypeError):
                            start_pos = 0
                            end_pos = len(segment_content)

                    segment = TextSegmentStyle(
                        content=segment_content,
                        start=start_pos,
                        end=end_pos,
                        fontSize=to_sp(segment_size),
                        fontFamily=segment_font,
                        fontWeight=parse_font_weight(segment_font),
                        color=parse_color(segment_color_data) or "#000000",
                        lineHeight=to_sp(style_item.get('line', font.get('line', 0)))
                    )
                    segments.append(segment)

                text.segments = segments

        return text

    def _extract_slices(self):
        """
        提取切图清单（兼容新旧 JSON 结构）

        新版结构 (2026+): image.imageUrl / image.svgUrl
        旧版结构 (2025-): ddsImage.imageUrl
        """
        # 构建 layer_path 映射（图层ID -> 完整路径）
        layer_paths = self._build_layer_paths()

        for layer_id, layer in self.layers.items():
            download_url = ''
            svg_url = ''
            format_type = 'png'
            metadata = {}

            # ===== 新版结构 (优先) =====
            image_info = layer.get('image', {})
            if image_info:
                download_url = image_info.get('imageUrl', '')
                svg_url = image_info.get('svgUrl', '')
                if svg_url and not download_url:
                    download_url = svg_url
                    format_type = 'svg'
                # 提取 MCP metadata
                metadata = self._extract_slice_metadata(layer)

            # ===== 旧版结构 (兼容) =====
            if not download_url:
                dds_image = layer.get('ddsImage', {})
                if dds_image and dds_image.get('imageUrl'):
                    download_url = dds_image.get('imageUrl')
                    metadata = self._extract_slice_metadata(layer)

            # ===== 位图引用 =====
            if not download_url:
                bitmap_ref = layer.get('image', {}).get('_ref', '')
                if bitmap_ref:
                    # 构建位图 URL (蓝湖 OSS 格式)
                    if bitmap_ref.startswith('images/'):
                        hash_part = bitmap_ref.replace('images/', '')
                        download_url = f"https://lanhu-oss-proxy.lanhuapp.com/SketchPng{hash_part}"

            # ===== 切图识别条件（优化版 v3 - 切图优先）=====
            # 核心原则：有下载链接 = 有切图，优先使用切图而非手写 shape

            # 优先级1: 有下载链接（最关键！设计稿已提供切图资源）
            has_download_url = bool(download_url)

            # 优先级2: 明确标注为可导出的图层
            is_explicit_export = (
                layer.get('exportable') or
                layer.get('hasExportSizes') or
                layer.get('type') == 'slice' or
                layer.get('_class') == 'slice'
            )

            # 优先级3: 名称前缀匹配（独立图标/图片）
            layer_name_lower = layer.get('name', '').lower()
            is_named_slice = layer_name_lower.startswith(('icon_', 'img_', 'bg_', 'btn_', 'ic_', 'divider_'))

            # ===== 过滤条件（放宽版）=====
            width = layer.get('width', 0)
            height = layer.get('height', 0)

            # 过滤1: 尺寸过滤（最小50x50px，但如果有下载链接则放宽到20x20）
            MIN_SIZE_WITH_URL = 20  # 有切图链接时放宽尺寸要求
            MIN_SIZE_NO_URL = 50    # 无切图链接时保持原要求
            size_ok = (
                (width >= MIN_SIZE_WITH_URL and height >= MIN_SIZE_WITH_URL) if has_download_url
                else (width >= MIN_SIZE_NO_URL and height >= MIN_SIZE_NO_URL)
            ) or is_explicit_export

            # 过滤2: 内部元素过滤 - 有下载链接时不再跳过！
            # 设计稿提供的切图应该优先使用，即使图层名包含 rect/shape 等
            internal_keywords = ['rect', 'mask', 'oval', 'path', 'line', 'triangle', 'shape']
            is_internal_element = any(kw in layer_name_lower for kw in internal_keywords)
            # 关键修改：有下载链接时，即使名称包含内部关键词，也识别为切图
            skip_internal = is_internal_element and not has_download_url and not is_explicit_export and (width < 100 or height < 100)

            # 过滤3: 检查父级是否已有完整切图（修复：用 ID + 链接双重验证）
            # 如果父级Group真的有切图链接，则跳过子元素（避免重复）
            # 但图标类图层是明确独立的，不应该被过滤
            parent_has_slice = False
            layer_path = layer_paths.get(layer_id, '')

            # 增强版图标识别：检查多种图标前缀变体
            # 包括: icon/, Icon/, ICON/, 图标/, ic_, Icon_, IC_
            layer_name_raw = layer.get('name', '')
            is_icon_layer = (
                layer_name_lower.startswith('icon/') or
                layer_name_lower.startswith('图标/') or
                layer_name_raw.startswith('Icon/') or
                layer_name_raw.startswith('ICON/') or
                layer_name_lower.startswith('ic_') or
                layer_name_raw.startswith('Icon_') or
                layer_name_raw.startswith('IC_') or
                'icon/' in layer_name_lower or
                '图标/' in layer_name_raw
            )

            if '/' in layer_path and has_download_url and not is_icon_layer:
                # 修复：改用 parentID 精确匹配，而非名称匹配
                # 避免同名图层误判（如多个 "编组 2"）
                parent_id = layer.get('parentID')
                parent_layer = self.layers.get(parent_id)

                if parent_layer:
                    # 1. 检查父级是否真的有切图下载链接（而非只在切图列表中）
                    parent_has_download_url = bool(
                        parent_layer.get('ddsImage', {}).get('imageUrl') or
                        parent_layer.get('image', {}).get('imageUrl')
                    )

                    # 2. 只有父级有真实链接 + 在切图列表中，才认为父级已有切图
                    #    这样可以避免同名图层误判
                    if parent_has_download_url and parent_id in self.slice_map:
                        parent_has_slice = True

            # 最终判断（只提取设计师明确标记为导出的切图）
            # 蓝湖网页上只有 exportable=true 的图层才显示为有效切图
            # 必须同时满足: exportable=true + 有下载链接
            is_slice = (
                is_explicit_export and
                has_download_url and
                size_ok and
                not skip_internal and
                not parent_has_slice
            )

            if is_slice:
                layer_name = layer.get('name', 'unknown')

                # ⚠️ 切图尺寸优先使用 image.size（蓝湖网页显示的真实标注尺寸）
                # layer.width/height 不是标注尺寸，image.size 才是
                image_info = layer.get('image', {})
                image_size = image_info.get('size', {})
                if image_size and image_size.get('width') and image_size.get('height'):
                    # 使用 image.size 作为标注尺寸（蓝湖真实尺寸）
                    slice_width = int(image_size.get('width'))
                    slice_height = int(image_size.get('height'))
                else:
                    # fallback 到 layer.width/height
                    slice_width = int(width)
                    slice_height = int(height)

                # 使用已有的 layer_path（在过滤条件中已获取）
                if not layer_path:
                    layer_path = layer_name

                # 获取上下文信息
                context_info = self._get_layer_context(layer_id, layer)
                context_info['layer_path'] = layer_path  # 新增：图层路径

                # 生成切图名称（传入 layer_path 和 layer）
                slice_name = generate_slice_name(
                    layer_name,
                    context_info=context_info,
                    layer_path=layer_path,
                    layer=layer  # 传入完整图层数据用于尺寸判断
                )

                # 确定目标目录
                name_lower = slice_name.lower()
                if name_lower.startswith('ic_'):
                    asset_subdir = "icons"
                elif name_lower.startswith('bg_'):
                    asset_subdir = "backgrounds"
                elif name_lower.startswith('btn_'):
                    asset_subdir = "buttons"
                elif name_lower.startswith('divider_'):
                    asset_subdir = "images"
                else:
                    asset_subdir = "images"

                # 本地相对路径
                local_path = f"assets/{asset_subdir}/{slice_name}"

                # Android drawable 资源名（不含扩展名）
                drawable_name = slice_name.rsplit('.', 1)[0]

                # 切图尺寸：使用 image.size 作为标注尺寸（蓝湖网页显示的真实标注）
                actual_size = f"{slice_width}x{slice_height}"

                slice_item = SliceItem(
                    name=slice_name,
                    format=format_type,
                    density="xxhdpi",
                    size=f"{slice_width}x{slice_height}",  # 标注尺寸（蓝湖真实尺寸）
                    actual_size=actual_size,
                    source_layer=layer_name,
                    node_id=layer_id,
                    node_x=self._to_dp(layer.get('left', 0)),
                    node_y=self._to_dp(layer.get('top', 0)),
                    ancestor_path=layer_path,
                    download_url=download_url,
                    svg_url=svg_url,
                    local_path=local_path,
                    drawable_name=drawable_name,
                    status="available",
                    scale=self.slice_scale
                )
                self.slices.append(slice_item)
                self.slice_map[layer_id] = slice_item

        # 去重：相同 download_url 只保留一个
        seen_urls = set()
        unique_slices = []
        for s in self.slices:
            if s.download_url not in seen_urls:
                seen_urls.add(s.download_url)
                unique_slices.append(s)
        dup_count = len(self.slices) - len(unique_slices)
        if dup_count > 0:
            print(f"切图去重: 移除 {dup_count} 个重复项")
        self.slices = unique_slices

    def _build_layer_paths(self) -> Dict[str, str]:
        """
        构建图层路径映射（图层ID -> 完整路径）

        Returns:
            dict: {layer_id: "Parent/Child/GrandChild"}
        """
        paths = {}

        def build_path(layer_id: str, current_path: str = ""):
            layer = self.layers.get(layer_id, {})
            layer_name = layer.get('name', 'Unknown')

            # 构建当前路径
            if current_path:
                new_path = f"{current_path}/{layer_name}"
            else:
                new_path = layer_name

            paths[layer_id] = new_path

            # 递归处理子图层
            child_ids = self.layer_tree.get(layer_id, [])
            for child_id in child_ids:
                build_path(child_id, new_path)

        # 从画板开始构建路径
        for artboard_id in self.artboards.keys():
            build_path(artboard_id, "")

        # 处理不属于任何画板的图层（可能在外部）
        for layer_id in self.layers.keys():
            if layer_id not in paths:
                parent_id = self.layers[layer_id].get('parentID')
                if parent_id and parent_id in paths:
                    parent_path = paths[parent_id]
                    layer_name = self.layers[layer_id].get('name', 'Unknown')
                    paths[layer_id] = f"{parent_path}/{layer_name}"
                else:
                    paths[layer_id] = self.layers[layer_id].get('name', 'Unknown')

        return paths

    def _extract_slice_metadata(self, layer: Dict) -> Dict:
        """
        提取切图元数据（MCP 格式）

        Args:
            layer: 图层数据

        Returns:
            dict: {fills, borders, shadows, opacity, border_radius, rotation, text_style}
        """
        metadata = {}

        # 填充
        fills = layer.get('fills', [])
        if fills:
            metadata['fills'] = []
            for fill in fills:
                if fill.get('isEnabled', True):
                    fill_data = {
                        'type': fill.get('type', 'color'),
                        'color': parse_color(fill.get('color')),
                        'opacity': fill.get('opacity', 1.0)
                    }
                    metadata['fills'].append(fill_data)

        # 边框
        borders = layer.get('borders', [])
        if borders:
            metadata['borders'] = []
            for border in borders:
                if border.get('isEnabled', True):
                    border_data = {
                        'thickness': border.get('thickness', 0),
                        'color': parse_color(border.get('color')),
                        'position': border.get('position', 0)
                    }
                    metadata['borders'].append(border_data)

        # 阴影
        shadows = layer.get('shadows', [])
        if shadows:
            metadata['shadows'] = []
            for shadow in shadows:
                if shadow.get('isEnabled', True):
                    shadow_data = {
                        'type': 'inner' if shadow.get('type') == 1 else 'outer',
                        'offsetX': shadow.get('offsetX', 0),
                        'offsetY': shadow.get('offsetY', 0),
                        'blurRadius': shadow.get('blurRadius', 0),
                        'spread': shadow.get('spread', 0),
                        'color': parse_color(shadow.get('color'))
                    }
                    metadata['shadows'].append(shadow_data)

        # 透明度
        opacity = layer.get('opacity', 100)
        if opacity != 100:
            metadata['opacity'] = opacity / 100.0

        # 圆角
        if 'fixedRadius' in layer:
            metadata['border_radius'] = round_metric(layer.get('fixedRadius', 0))
        else:
            points = layer.get('points', [])
            if points:
                radii = [round_metric(p.get('cornerRadius', 0)) for p in points if has_meaningful_value(p.get('cornerRadius', 0))]
                if radii:
                    metadata['border_radius'] = radii[0]

        # 旋转
        rotation = layer.get('rotation', 0)
        if rotation != 0:
            metadata['rotation'] = rotation

        # 文本样式（如果是文本图层）
        if layer.get('type') == 'text':
            font = layer.get('font', {})
            if font:
                metadata['text_style'] = {
                    'fontSize': round_metric(font.get('size', 0)),
                    'fontFamily': font.get('family', ''),
                    'fontWeight': font.get('weight', 400),
                    'lineHeight': round_metric(font.get('line', 0)),
                    'letterSpacing': round_metric(font.get('kerning', 0)),
                    'textAlign': font.get('align', 'left'),
                    'color': None
                }
                styles = font.get('styles', [])
                if styles and styles[0].get('color'):
                    metadata['text_style']['color'] = parse_color(styles[0].get('color'))

        return metadata

    def _get_layer_context(self, layer_id: str, layer: Dict) -> Dict:
        """获取图层的上下文信息，用于推断功能"""
        context = {
            'parent_name': '',
            'sibling_texts': [],
            'nearby_text': '',
            'position': '',
        }

        # 获取父节点名称
        parent_id = layer.get('parentID')
        if parent_id and parent_id in self.layers:
            parent = self.layers[parent_id]
            context['parent_name'] = parent.get('name', '')

        # 获取兄弟节点中的文本
        if parent_id:
            sibling_ids = self.layer_tree.get(parent_id, [])
            layer_y = layer.get('top', 0)
            layer_x = layer.get('left', 0)

            for sibling_id in sibling_ids:
                if sibling_id == layer_id:
                    continue
                sibling = self.layers.get(sibling_id, {})
                if sibling.get('type') == 'text':
                    text_content = sibling.get('name', '')
                    sibling_y = sibling.get('top', 0)
                    sibling_x = sibling.get('left', 0)

                    # 计算距离，优先取最近的文本
                    distance = abs(sibling_y - layer_y) + abs(sibling_x - layer_x)

                    context['sibling_texts'].append({
                        'text': text_content,
                        'distance': distance,
                        'y': sibling_y,
                        'x': sibling_x,
                    })

            # 按距离排序，取最近的文本
            if context['sibling_texts']:
                context['sibling_texts'].sort(key=lambda x: x['distance'])
                context['nearby_text'] = context['sibling_texts'][0]['text']

        return context

    def _get_slice_for_layer(self, layer: Dict) -> Optional[SliceInfo]:
        """获取图层对应的切图信息"""
        layer_id = layer.get('id')
        if layer_id in self.slice_map:
            slice_item = self.slice_map[layer_id]
            return SliceInfo(
                name=slice_item.name,
                local_path=slice_item.local_path,
                drawable_name=slice_item.drawable_name,
                size=slice_item.size,
                status=slice_item.status
            )
        return None

    def save_outputs(self):
        """保存输出产物"""
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # annotations.json 对外只暴露 dp 语义，后续 XML 不再二次换算。
        dp_scale = self._dp_scale()

        # 保存结构化标注
        annotations_file = self.output_dir / "annotations.json"
        annotations_data = {
            # 顶层 scale 信息
            "scale_info": {
                "sliceScale": self.slice_scale,
                "artboardScale": 1.0,  # 画板缩放比例（默认 1）
                "dpScale": dp_scale,   # 设计稿密度系数（从画板宽度推断，用于切图导出）
                "pixelDensity": 3 if dp_scale == 3.0 else 1,
            },
            # 数值说明（重要：坐标/尺寸/圆角/字号已为 dp/sp 单位，禁止二次换算）
            "conversion_note": "数值已为 dp/sp 单位，直接使用。dpScale 是切图导出倍率，不是坐标换算系数。",
        }

        # 添加各画板的组件树
        for name, tree in self.annotations.items():
            annotations_data[name] = self._node_to_dict(tree)

        with open(annotations_file, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=2)
        print(f"结构化标注已保存: {annotations_file}")

        # 输出密度信息摘要
        print(f"\n=== 密度信息 ===")
        print(f"sliceScale: {self.slice_scale} (切图导出倍率，不是坐标换算系数)")
        print(f"dpScale: {dp_scale} (设计稿密度系数)")
        print(f"单位说明: annotations.json 内坐标/尺寸/圆角/字号已是 dp/sp，直接使用，禁止二次换算")

        save_slices_file(self.output_dir, self.slices, self.slice_scale)
        save_issues_file(self.output_dir, self.issues)

        # 创建切图目录结构
        assets_dir = self.output_dir / "assets"
        (assets_dir / "icons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
        (assets_dir / "buttons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "images").mkdir(parents=True, exist_ok=True)

        print(f"切图目录已创建: {assets_dir}")

    def _node_to_dict(self, node: ComponentNode) -> Dict:
        """将节点转换为字典"""
        result = {
            "type": node.type,
            "name": node.name,
            "layerId": node.layerId,
            "position": node.position,  # 包含 px 和 dp 单位
            "style": asdict(node.style),
        }

        # 排列方向（新增字段）
        if node.orientation:
            result["orientation"] = node.orientation

        # 与兄弟元素的间距（新增字段）
        if node.sibling_gap:
            result["sibling_gap"] = node.sibling_gap

        if node.text:
            result["text"] = asdict(node.text)
        if node.slice:
            result["slice"] = asdict(node.slice)
        if node.states:
            result["states"] = node.states
        if node.children:
            result["children"] = [self._node_to_dict(c) for c in node.children]
        return result

    def _get_primary_artboard_width(self) -> float:
        """获取主画板宽度（用于推断密度系数）。

        优先从 self.artboards 读取（Sketch 流程），
        Figma 流程下 artboards 为空则回退到 self.artboard_frame。
        """
        if self.artboards:
            first = list(self.artboards.values())[0]
            return float(first.get('width', 0))
        # Figma 流程：画板数据存在 self.artboard_frame 中
        if hasattr(self, 'artboard_frame') and self.artboard_frame:
            w = self.artboard_frame.get('width', 0)
            if w:
                return float(w)
        return 0

    def _dp_scale(self) -> float:
        """从画板宽度推断密度系数，替代 slice_scale。

        画板 ≤ 430px → 1x 设计，坐标值本身就是 dp，无需换算。
        画板 ≥ 1000px → 尝试用标准密度还原（1080÷3=360dp, 1440÷4=360dp等）。
        """
        w = self._get_primary_artboard_width()
        if w <= 0:
            return 1.0
        if w <= 430:
            return 1.0
        for factor in (4.0, 3.0, 2.0, 1.5):
            dp_w = w / factor
            if 320 <= dp_w <= 430 and abs(dp_w - round(dp_w)) < 0.1:
                return factor
        return 1.0

    def _to_dp(self, value: Any) -> float:
        """把原始 px 标注转换为 Android dp，保留两位小数。"""
        try:
            numeric = float(value or 0)
        except (TypeError, ValueError):
            return 0
        scale = self._dp_scale()
        converted = numeric / scale if scale > 1 else numeric
        return round(converted, 2)

    def _scaled_shadow(self, shadow: Dict) -> Dict:
        """阴影几何参数按 dp 输出，颜色和类型保持原样。"""
        scaled = dict(shadow)
        for key in ("offsetX", "offsetY", "blur", "spread"):
            if key in scaled:
                scaled[key] = self._to_dp(scaled[key])
        return scaled

    def _infer_visual_role(self, node: ComponentNode) -> Dict:
        """为 XML/Compose 生成提供轻量语义提示，减少后续凭名字猜测。"""
        name = (node.name or "").lower()
        width = node.position.get("width_dp", 0)
        height = node.position.get("height_dp", 0)
        role = "container" if node.children else "shape"
        android_view = "ConstraintLayout" if node.children else "View"
        render_mode = "compose_children"

        if node.text:
            role = "text"
            android_view = "TextView"
            render_mode = "text"
        elif node.slice:
            if "tab" in name:
                role = "tab_bar"
            elif "btn" in name or "button" in name or "按钮" in node.name or "点击" in node.name:
                role = "button_asset"
            elif width <= 40 and height <= 40:
                role = "icon"
            elif width >= 160 or height >= 120:
                role = "image_or_background"
            else:
                role = "image"
            android_view = "ImageView"
            render_mode = "slice_only"
        elif node.type in ("Rectangle", "Oval"):
            role = "background" if width >= 120 or height >= 80 else "shape"
            android_view = "View"
            render_mode = "shape"

        hint = {
            "role": role,
            "androidView": android_view,
            "renderMode": render_mode,
        }
        if node.slice:
            hint["preferSlice"] = True
        return hint

    def _node_to_dict_compact(self, node: ComponentNode) -> Dict:
        """
        紧凑版节点转换（优化 annotations.json 读取效率）

        优化点：
        - 只存 dp 单位（删除 px）
        - 只存非默认值（删除默认字段）
        - children 改为 ID 列表（扁平化）
        """
        result = {
            "id": node.layerId,
            "name": node.name,
            "type": node.type,
        }

        # position：存 dp 单位 + 绝对坐标（供跨层级对齐检测）
        position = node.position
        result["x"] = round(position.get("x_dp", 0), 2)
        result["y"] = round(position.get("y_dp", 0), 2)
        result["width"] = round(position.get("width_dp", 0), 2)
        result["height"] = round(position.get("height_dp", 0), 2)
        if "_absX" in position:
            result["absX"] = position["_absX"]
        elif "absoluteX" in position:
            result["absX"] = self._to_dp(position["absoluteX"])
        if "_absY" in position:
            result["absY"] = position["_absY"]
        elif "absoluteY" in position:
            result["absY"] = self._to_dp(position["absoluteY"])
        if "parentRelative" in position:
            result["parentX"] = position["parentRelative"]["x"]
            result["parentY"] = position["parentRelative"]["y"]

        # style：只存非默认值
        style_compact = {}
        style = node.style

        # 合并 opacity 到颜色（优先合并，避免 AI 手动计算）
        style_merged_opacity = False
        if style.opacity < 1.0:
            if style.backgroundColor and style.backgroundColor != "#00000000":
                merged_bg = apply_opacity_to_color(style.backgroundColor, style.opacity)
                style_compact["backgroundColor"] = merged_bg
                style_merged_opacity = True
            if style.borderColor:
                merged_border = apply_opacity_to_color(style.borderColor, style.opacity)
                style_compact["borderColor"] = merged_border
                style_merged_opacity = True

        # 背景色：如果上面没有合并 opacity，且颜色非透明，直接输出
        if style.backgroundColor and style.backgroundColor != "#00000000" and not style_merged_opacity:
            style_compact["backgroundColor"] = style.backgroundColor

        # 圆角（统一圆角）
        if style.borderRadius > 0:
            style_compact["borderRadius"] = self._to_dp(style.borderRadius)
        # 或单独圆角（有不一致的）
        elif (style.borderTopLeftRadius > 0 or style.borderTopRightRadius > 0 or
              style.borderBottomLeftRadius > 0 or style.borderBottomRightRadius > 0):
            radii = {}
            if style.borderTopLeftRadius > 0:
                radii["topLeft"] = self._to_dp(style.borderTopLeftRadius)
            if style.borderTopRightRadius > 0:
                radii["topRight"] = self._to_dp(style.borderTopRightRadius)
            if style.borderBottomLeftRadius > 0:
                radii["bottomLeft"] = self._to_dp(style.borderBottomLeftRadius)
            if style.borderBottomRightRadius > 0:
                radii["bottomRight"] = self._to_dp(style.borderBottomRightRadius)
            if radii:
                style_compact["borderRadii"] = radii

        # 边框（有边框）
        if style.borderWidth > 0:
            style_compact["borderWidth"] = self._to_dp(style.borderWidth)
            # borderColor 已在 opacity 合并阶段处理；若 borderWidth>0 但无 borderColor，需单独处理
            if style.borderColor and not style_merged_opacity:
                style_compact["borderColor"] = style.borderColor

        # 仅当 opacity 没有合并到任何颜色时才保留独立字段
        if style.opacity < 1.0 and not style_merged_opacity:
            style_compact["opacity"] = round(style.opacity, 2)

        # 阴影（有阴影）
        if style.shadow:
            style_compact["shadow"] = self._scaled_shadow(style.shadow)

        # margin/padding：只存非全0的情况
        if style.margin and any(v > 0 for v in style.margin):
            style_compact["margin"] = [self._to_dp(v) for v in style.margin]
        if style.padding and any(v > 0 for v in style.padding):
            style_compact["padding"] = [self._to_dp(v) for v in style.padding]

        if style_compact:
            result["style"] = style_compact

        # slice：简化格式
        if node.slice:
            result["slice"] = {
                "drawable": node.slice.drawable_name,
                "size": node.slice.size
            }

        # text：保留必要字段
        if node.text:
            text_compact = {
                "content": node.text.content,
                "fontSize": node.text.fontSize,
            }
            if has_meaningful_value(node.text.lineHeight):
                text_compact["lineHeight"] = node.text.lineHeight
            if has_meaningful_value(node.text.letterSpacing):
                text_compact["letterSpacing"] = node.text.letterSpacing
            if node.text.fontFamily:
                text_compact["fontFamily"] = node.text.fontFamily
            if node.text.color and node.text.color != "#000000":
                text_compact["color"] = node.text.color
            if node.text.fontWeight and node.text.fontWeight != 400:
                text_compact["fontWeight"] = node.text.fontWeight
            if node.text.textAlign and node.text.textAlign != "left":
                text_compact["textAlign"] = node.text.textAlign

            # 富文本分段样式（当有多个分段且样式不同时）
            if node.text.segments and len(node.text.segments) > 1:
                # 检查是否有实际差异（颜色或字重）
                has_color_diff = any(s.color != node.text.segments[0].color for s in node.text.segments)
                has_weight_diff = any(s.fontWeight != node.text.segments[0].fontWeight for s in node.text.segments)
                has_size_diff = any(abs(s.fontSize - node.text.segments[0].fontSize) > 1e-6 for s in node.text.segments)
                has_line_height_diff = any(abs(s.lineHeight - node.text.segments[0].lineHeight) > 1e-6 for s in node.text.segments)
                has_font_family_diff = any(s.fontFamily != node.text.segments[0].fontFamily for s in node.text.segments)
                if has_color_diff or has_weight_diff or has_size_diff or has_line_height_diff or has_font_family_diff:
                    segments_compact = []
                    for seg in node.text.segments:
                        seg_data = {
                            "content": seg.content,
                            "start": seg.start,
                            "end": seg.end,
                        }
                        if seg.color and seg.color != "#000000":
                            seg_data["color"] = seg.color
                        if seg.fontWeight and seg.fontWeight != 400:
                            seg_data["fontWeight"] = seg.fontWeight
                        if has_meaningful_value(seg.fontSize):
                            seg_data["fontSize"] = seg.fontSize
                        if seg.fontFamily:
                            seg_data["fontFamily"] = seg.fontFamily
                        if has_meaningful_value(seg.lineHeight):
                            seg_data["lineHeight"] = seg.lineHeight
                        segments_compact.append(seg_data)
                    text_compact["segments"] = segments_compact

            result["text"] = text_compact

        # orientation：有值才存
        if node.orientation:
            result["orientation"] = node.orientation

        # sibling_gap：有值才存
        if node.sibling_gap:
            result["siblingGap"] = node.sibling_gap

        # parentMargins：首/尾子元素的父容器边距（_enrich_tree 补全）
        pm = node.position.get("parentMargins")
        if pm:
            result["parentMargins"] = pm

        # children：改为 ID 列表（扁平化关键点）
        if node.children:
            result["children"] = [c.layerId for c in node.children]

        result["renderHint"] = self._infer_visual_role(node)

        return result

    def _enrich_tree(self):
        """后处理：补全 siblingGap、parentMargins，并进行布局语义分析"""
        # 收集所有节点信息用于跨层级分析
        self._all_nodes_flat = []  # [{id, name, type, absX, absY, width, height, parent, level}]
        for name, tree in self.annotations.items():
            self._enrich_node(tree)

        # 布局语义分析
        self._analyze_layout()

    def _enrich_node(self, node: ComponentNode):
        """递归补全单个节点的布局信息"""
        children = node.children

        # 收集自身信息
        dp_scale = self._dp_scale()
        abs_x = node.position.get("absoluteX", node.position.get("x_px", node.position.get("x", 0)))
        abs_y = node.position.get("absoluteY", node.position.get("y_px", node.position.get("y", 0)))
        if dp_scale > 1:
            abs_x = round(abs_x / dp_scale, 2)
            abs_y = round(abs_y / dp_scale, 2)
        node.position["_absX"] = abs_x
        node.position["_absY"] = abs_y

        if not children:
            return

        pw = node.position.get("width_dp", node.position.get("width", 0))
        ph = node.position.get("height_dp", node.position.get("height", 0))

        # 子元素类型统计
        child_types = [c.type for c in children]
        has_text_child = "Text" in child_types
        has_group_child = "Group" in child_types
        unique_types = set(child_types)

        # 容器类型推断
        if len(children) == 1 and children[0].type == "Rectangle":
            # 只有1个矩形子元素 → FrameLayout（矩形当背景）+ 子元素可能是内容区
            node.position["_layoutHint"] = "FrameLayout"
        elif node.orientation == "vertical":
            node.position["_layoutHint"] = "LinearLayout"
        elif node.orientation == "horizontal":
            node.position["_layoutHint"] = "LinearLayout"
        elif len(children) >= 3 and self._has_repeated_structure(children):
            node.position["_layoutHint"] = "RecyclerView"
        else:
            node.position["_layoutHint"] = "ConstraintLayout"

        # 扁平化检测：透传 Group
        if node.type == "Group":
            if len(children) == 1:
                node.position["_shouldFlatten"] = True
            elif not has_group_child and not has_text_child and all(c.type == "Rectangle" or c.type == "Image" for c in children):
                # 纯视觉组（全部是矩形/图片）→ 可能应扁平化
                pass  # 不下判断，留给 AI 决定

        for i, child in enumerate(children):
            # below/right = 下一个兄弟的 above/left
            if i < len(children) - 1:
                nxt = children[i + 1]
                if "above" in nxt.sibling_gap and "below" not in child.sibling_gap:
                    child.sibling_gap["below"] = nxt.sibling_gap["above"]
                if "left" in nxt.sibling_gap and "right" not in child.sibling_gap:
                    child.sibling_gap["right"] = nxt.sibling_gap["left"]

            # 父容器边距：Sketch left/top 是画板绝对坐标，必须先转成相对父容器坐标
            parent_abs_x = node.position.get("_absX", 0)
            parent_abs_y = node.position.get("_absY", 0)
            child_abs_x = self._to_dp(child.position.get("x_px", child.position.get("x", 0)))
            child_abs_y = self._to_dp(child.position.get("y_px", child.position.get("y", 0)))
            cx = round(child_abs_x - parent_abs_x, 2)
            cy = round(child_abs_y - parent_abs_y, 2)
            child.position["parentRelative"] = {"x": cx, "y": cy}
            cw = child.position.get("width_dp", child.position.get("width", 0))
            ch = child.position.get("height_dp", child.position.get("height", 0))

            margins = {}
            if i == 0 and cy > 0:
                margins["top"] = round(cy, 2)
            if i == len(children) - 1 and ph > 0:
                bm = ph - (cy + ch)
                if bm > 0:
                    margins["bottom"] = round(bm, 2)
            if cx > 0:
                margins["start"] = round(cx, 2)
            if pw > 0:
                em = pw - (cx + cw)
                if em > 0:
                    margins["end"] = round(em, 2)

            if margins:
                child.position["parentMargins"] = margins

        for child in children:
            self._enrich_node(child)

    @staticmethod
    def _has_repeated_structure(children: List[ComponentNode]) -> bool:
        """检测子元素是否有重复结构（RecyclerView 特征）"""
        if len(children) < 3:
            return False

        def signature(c: ComponentNode) -> tuple:
            child_sigs = tuple(sorted(
                signature(gc) for gc in c.children
            )) if c.children else ()
            return (c.type, len(c.children), bool(c.text), child_sigs)

        sigs = [signature(c) for c in children]
        # 如果最常见的签名出现 >= 2 次且超过一半 → 重复模式
        from collections import Counter
        most_common = Counter(sigs).most_common(1)[0]
        return most_common[1] >= 2 and most_common[1] >= len(children) // 2

    def _analyze_layout(self):
        """布局语义分析：检测对齐组、重复模式、生成 layoutAnalysis"""
        alignment_groups = []
        repeat_patterns = []
        container_hints = {}
        flatten_candidates = []

        # 收集所有节点（用于对齐分析）
        all_nodes = []
        for name, tree in self.annotations.items():
            self._collect_nodes(tree, all_nodes)

        # 对齐组检测
        alignment_groups = self._detect_alignment_groups(all_nodes)

        # 重复模式检测
        for name, tree in self.annotations.items():
            self._detect_repeat_patterns(tree, repeat_patterns)

        # 容器类型提示收集
        for n in all_nodes:
            hint = n.get("_layoutHint")
            if hint:
                container_hints[n["id"]] = hint
            if n.get("_shouldFlatten"):
                flatten_candidates.append(n["id"])

        self.layout_analysis = {
            "alignmentGroups": alignment_groups,
            "repeatPatterns": repeat_patterns,
            "containerHints": container_hints,
            "flattenCandidates": flatten_candidates,
        }

        print(f"布局分析完成: {len(alignment_groups)} 个对齐组, "
              f"{len(repeat_patterns)} 个重复模式, "
              f"{len(flatten_candidates)} 个扁平化候选项")

    def _collect_nodes(self, node: ComponentNode, result: List[Dict],
                        parent_abs_x: float = 0, parent_abs_y: float = 0, level: int = 0):
        """递归收集所有节点信息，累积计算全局坐标"""
        dp_scale = self._dp_scale()
        pos = node.position

        # 全局绝对坐标：Sketch 图层 left/top 已是画板坐标，优先使用 _enrich_node 写入的值。
        local_x = pos.get("x_dp", pos.get("x", 0))
        local_y = pos.get("y_dp", pos.get("y", 0))
        global_x = local_x + parent_abs_x
        global_y = local_y + parent_abs_y

        # 如果有原始绝对坐标（Sketch 的 left/top），直接用（更可靠）
        raw_abs_x = pos.get("_absX")
        raw_abs_y = pos.get("_absY")
        if raw_abs_x is not None:
            global_x = raw_abs_x
        if raw_abs_y is not None:
            global_y = raw_abs_y

        info = {
            "id": node.layerId,
            "name": node.name,
            "type": node.type,
            "globalX": round(global_x, 2),
            "globalY": round(global_y, 2),
            "width": pos.get("width_dp", pos.get("width", 0)),
            "height": pos.get("height_dp", pos.get("height", 0)),
            "parent": node.parentId,
            "level": level,
            "has_text": bool(node.text),
            "has_slice": bool(node.slice),
            "children": [c.layerId for c in node.children] if node.children else [],
            "_layoutHint": pos.get("_layoutHint"),
            "_shouldFlatten": pos.get("_shouldFlatten", False),
        }
        result.append(info)
        for child in node.children:
            self._collect_nodes(child, result, global_x, global_y, level + 1)

    @staticmethod
    def _detect_alignment_groups(all_nodes: List[Dict]) -> List[Dict]:
        """检测对齐组（相同 globalX / 相同 globalCenterX / 相同 globalY 的元素）"""
        tolerance = 2.0  # dp 容差

        def group_by(items: List[Dict], key_fn, group_type: str):
            result = []
            sorted_items = sorted(items, key=key_fn)
            if not sorted_items:
                return result
            current_group = [sorted_items[0]]
            for i in range(1, len(sorted_items)):
                prev_val = key_fn(sorted_items[i - 1])
                curr_val = key_fn(sorted_items[i])
                if abs(curr_val - prev_val) <= tolerance:
                    current_group.append(sorted_items[i])
                else:
                    if len(current_group) >= 2:
                        result.append({
                            "type": group_type,
                            "value": round(key_fn(current_group[0]), 1),
                            "ids": [n["id"] for n in current_group],
                        })
                    current_group = [sorted_items[i]]
            if len(current_group) >= 2:
                result.append({
                    "type": group_type,
                    "value": round(key_fn(current_group[0]), 1),
                    "ids": [n["id"] for n in current_group],
                })
            return result

        # 只分析有实际布局意义的节点（非 Artboard、非容器 Group 的空壳）
        nodes = [n for n in all_nodes
                 if n["type"] != "Artboard"
                 and (n["has_text"] or n["has_slice"] or n["type"] in ("Rectangle", "Image", "Oval", "Text"))]

        groups = []
        groups.extend(group_by(nodes, lambda n: n["globalX"], "left"))
        groups.extend(group_by(nodes, lambda n: n["globalX"] + n["width"] / 2, "centerX"))
        groups.extend(group_by(nodes, lambda n: n["globalY"], "top"))
        return groups

    def _detect_repeat_patterns(self, node: ComponentNode, result: List[Dict]):
        """递归检测重复模式（RecyclerView 候选）"""
        children = node.children
        if len(children) >= 3 and self._has_repeated_structure(children):
            # 按结构签名分组
            def sig(c):
                child_types = tuple(gc.type for gc in c.children) if c.children else ()
                return (c.type, len(c.children), child_types)

            from collections import defaultdict
            groups = defaultdict(list)
            for c in children:
                groups[sig(c)].append(c.layerId)

            for sig_val, ids in groups.items():
                if len(ids) >= 2:
                    result.append({
                        "containerId": node.layerId,
                        "itemIds": ids,
                        "count": len(ids),
                        "suggestedType": "RecyclerView",
                    })

        for child in children:
            self._detect_repeat_patterns(child, result)

    def save_outputs_compact(self):
        """
        紧凑版输出（优化 annotations.json 读取效率）

        输出三层结构：
        - scale_info: 全局信息（必读，<50行）
        - index: 节点扁平索引（<500行，包含所有节点概览）
        - nodes: 节点详细数据（按需读取）
        """
        # 先补全布局信息
        self._enrich_tree()

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # _dp_scale() 从画板宽度推断密度系数，替代 slice_scale
        dp_scale = self._dp_scale()

        # 第1层：scale_info
        scale_info = {
            "sliceScale": self.slice_scale,
            "artboardScale": 1.0,
            "dpScale": dp_scale,
            "conversion_note": "数值已为 dp/sp 单位，直接使用。dpScale 是切图导出倍率，不是坐标换算系数。",
        }

        # 第2层：index（扁平索引）
        # 第3层：nodes（详细数据）
        index = {}
        nodes_compact = {}

        for artboard_name, tree in self.annotations.items():
            self._build_flat_index(
                tree, index, nodes_compact,
                level=0, parent_id=None
            )

        # 组合输出
        annotations_data = {
            "_unit": "dp",  # 所有坐标/尺寸/圆角/字号字段的单位标记
            "scale": scale_info,
            "artboard": {
                "name": list(self.annotations.keys())[0] if self.annotations else "Unknown",
                "root": tree.layerId if self.annotations else ""
            },
            "index": index,
            "nodes": nodes_compact,
            "layoutAnalysis": self.layout_analysis if hasattr(self, 'layout_analysis') else {},
        }

        # 紧凑格式保存（indent=1）
        annotations_file = self.output_dir / "annotations.json"
        with open(annotations_file, 'w', encoding='utf-8') as f:
            json.dump(annotations_data, f, ensure_ascii=False, indent=1)
        print(f"结构化标注已保存（紧凑格式）: {annotations_file}")
        print(f"节点总数: {len(index)}, 切图节点: {sum(1 for v in index.values() if v.get('has_slice'))}")

        # 输出密度信息摘要
        print(f"\n=== 密度信息 ===")
        print(f"sliceScale: {self.slice_scale} (切图导出倍率，不是坐标换算系数)")
        print(f"dpScale: {dp_scale} (设计稿密度系数)")
        print(f"单位说明: annotations.json 内坐标/尺寸/圆角/字号已是 dp/sp，直接使用，禁止二次换算")

        # 保存切图清单（紧凑格式）
        save_slices_file(self.output_dir, self.slices, self.slice_scale)
        save_issues_file(self.output_dir, self.issues)

        # 创建切图目录结构
        assets_dir = self.output_dir / "assets"
        (assets_dir / "icons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
        (assets_dir / "buttons").mkdir(parents=True, exist_ok=True)
        (assets_dir / "images").mkdir(parents=True, exist_ok=True)
        print(f"切图目录已创建: {assets_dir}")

    def _build_flat_index(self, node: ComponentNode, index: Dict, nodes: Dict,
                           level: int, parent_id: Optional[str]):
        """
        递归构建扁平索引

        Args:
            node: 当前节点
            index: 累积的索引字典
            nodes: 累积的节点详细数据字典
            level: 当前嵌套层级（0=根节点）
            parent_id: 父节点 ID
        """
        # 索引条目（概览信息）
        entry = {
            "name": node.name,
            "type": node.type,
            "level": level,
            "parent": parent_id,
            "children": [c.layerId for c in node.children] if node.children else [],
            "has_slice": bool(node.slice),
            "has_text": bool(node.text),
        }
        # 快速布局提示
        if node.orientation:
            entry["orientation"] = node.orientation
        pm = node.position.get("parentMargins")
        if pm:
            entry["parentMargins"] = pm
        index[node.layerId] = entry

        # 节点详细数据（紧凑格式）
        nodes[node.layerId] = self._node_to_dict_compact(node)

        # 递归处理子节点
        for child in node.children:
            self._build_flat_index(child, index, nodes, level + 1, node.layerId)

    def download_slices(self, max_workers: int = 5):
        """下载切图资源"""
        download_slice_assets(self, max_workers=max_workers)

    def download_screenshot(self, screenshot_url: str) -> Optional[str]:
        """下载页面截图"""
        return save_screenshot_resource(self.output_dir, screenshot_url)

    def validate_structure(self) -> List[Dict]:
        """验证结构化标注与设计稿的一致性"""
        issues = []

        for artboard_name, tree in self.annotations.items():
            # 检查画板尺寸
            if tree.style.width == 0 or tree.style.height == 0:
                issues.append({
                    "type": "标注缺失",
                    "screen": artboard_name,
                    "layer": tree.name,
                    "description": "画板尺寸为0",
                    "workaround": None
                })

            # 递归检查子节点
            self._validate_node(tree, artboard_name, issues)

        return issues

    def _validate_node(self, node: ComponentNode, screen_name: str, issues: List[Dict]):
        """验证单个节点"""
        # 检查必要属性
        if not node.name or node.name == 'Unknown':
            issues.append({
                "type": "标注缺失",
                "screen": screen_name,
                "layer": node.layerId,
                "description": "图层名称缺失",
                "workaround": None
            })

        # 检查尺寸
        if node.style.width > 0 and node.style.height > 0:
            # 检查是否有切图但状态为missing
            if node.slice and node.slice.status == "missing":
                issues.append({
                    "type": "切图缺失",
                    "screen": screen_name,
                    "layer": node.name,
                    "description": f"切图 {node.slice.name} 下载失败",
                    "workaround": "使用标注参数或占位图替代"
                })

        # 检查文本图层
        if node.type == 'Text' and node.text:
            if not node.text.content:
                issues.append({
                    "type": "标注缺失",
                    "screen": screen_name,
                    "layer": node.name,
                    "description": "文本内容为空",
                    "workaround": None
                })
            if node.text.fontSize == 0:
                issues.append({
                    "type": "标注缺失",
                    "screen": screen_name,
                    "layer": node.name,
                    "description": "文本字号为0",
                    "workaround": None
                })

        # 递归检查子节点
        for child in node.children:
            self._validate_node(child, screen_name, issues)


# ==================== 主函数 ====================

def main():
    parser = argparse.ArgumentParser(description='蓝湖设计稿JSON解析工具（支持 Sketch 和 Figma 格式）')
    parser.add_argument('json_path', nargs='?', help='JSON文件路径或蓝湖项目URL')
    parser.add_argument('--output', '-o', default='./output', help='输出目录')
    parser.add_argument('--no-download', action='store_true', help='跳过切图下载（默认自动下载并按 sliceScale 缩放回正确尺寸）')
    parser.add_argument('--screenshot', help='页面截图URL')
    parser.add_argument('--validate', '-v', action='store_true', help='验证结构化标注')
    parser.add_argument('--screen', '-s', help='指定画板名称')
    parser.add_argument('--all', '-a', action='store_true', help='处理所有画板')
    parser.add_argument('--force-refresh', action='store_true',
                        help='忽略本地同 design_id 的完整提取产物，强制重新下载 JSON/截图/切图')
    parser.add_argument('--format', '-f', choices=['auto', 'sketch', 'figma'], default='auto',
                        help='指定JSON格式（默认自动检测）')

    # URL 直连模式参数
    parser.add_argument('--url', help='蓝湖项目URL（如: https://lanhuapp.com/web/#/item/project/stage?tid=xxx&pid=xxx）')
    parser.add_argument('--list', '-l', action='store_true', help='列出设计图清单（配合--url使用）')
    parser.add_argument('--design', help='指定设计图ID或名称（配合--url使用）')
    parser.add_argument('--cookie', help='蓝湖登录Cookie（可选）')

    args = parser.parse_args()

    # ===== URL 直连模式 =====
    if args.url:
        client = LanhuAPIClient(cookie=args.cookie)
        url_info = client.parse_url(args.url)

        print(f"URL类型: {url_info['url_type']}")
        print(f"团队ID: {url_info['team_id']}")
        print(f"项目ID: {url_info['project_id']}")

        if url_info['url_type'] == 'invite':
            print("解析邀请链接...")
            url_info = client.resolve_invite_link(args.url)
            print(f"实际项目URL: {url_info['resolved_url']}")

        if not url_info['team_id'] or not url_info['project_id']:
            print("无法解析URL参数，请检查URL格式")
            return 1

        # 列出设计图清单
        if args.list:
            designs = client.get_designs(url_info['team_id'], url_info['project_id'])
            print(f"\n=== 设计图清单 ({len(designs)} 个) ===")
            for i, d in enumerate(designs, 1):
                print(f"{i}. [{d['id']}] {d['name']} - {d['width']}x{d['height']}")
            client.close()
            return 0

        # 获取设计图详情
        if args.design:
            designs = client.get_designs(url_info['team_id'], url_info['project_id'])
            target_design = None
            for d in designs:
                if d['id'] == args.design or d['name'] == args.design:
                    target_design = d
                    break
            if not target_design:
                print(f"未找到设计图: {args.design}")
                print("使用 --list 参数查看所有设计图")
                client.close()
                return 1
            design_id = target_design['id']
        else:
            designs = client.get_designs(url_info['team_id'], url_info['project_id'])
            if not designs:
                print("未获取到设计图列表")
                client.close()
                return 1
            design_id = designs[0]['id']
            print(f"自动选择第一个设计图: {designs[0]['name']}")

        # 获取设计图详情和 JSON URL
        detail = client.get_design_detail(design_id, url_info['team_id'], url_info['project_id'])
        if not detail or not detail.get('json_url'):
            print("获取设计图详情失败或无JSON数据")
            client.close()
            return 1

        json_url = detail['json_url']
        print(f"JSON URL: {json_url}")

        if reuse_existing_extract_if_complete(args.output, json_url, detail.get('url'),
                                              force_refresh=args.force_refresh):
            client.close()
            return 0

        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f'{design_id}.json')
        if reuse_existing_extract_if_complete(args.output, temp_path, detail.get('url'),
                                              force_refresh=args.force_refresh):
            client.close()
            return 0

        # 下载 JSON 数据
        json_data = client.get_sketch_json(json_url)
        client.close()

        if not json_data:
            print("下载JSON失败")
            return 1

        # 保存临时JSON文件（跨平台兼容，使用 design_id 作为文件名）
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False)
        json_path = temp_path

        # 设置页面截图URL
        screenshot_url = detail.get('url')
        original_url = None  # --url 模式下 design_id 已作为文件名，不需要原始 URL

    # ===== 本地 JSON / JSON URL 模式 =====
    elif args.json_path:
        json_path = args.json_path
        screenshot_url = args.screenshot
        original_url = None  # 保存原始 URL

        # 判断是URL还是本地文件
        if json_path.startswith('http'):
            original_url = json_path  # 保存原始 URL
            if reuse_existing_extract_if_complete(args.output, original_url, screenshot_url,
                                                  force_refresh=args.force_refresh):
                return 0
            # 下载JSON到临时文件（跨平台兼容）
            print(f"从URL下载JSON: {json_path}")
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, 'lanhu_temp.json')
            try:
                content = fetch_url_bytes(json_path, headers={'Accept-Encoding': 'gzip'}, timeout=60)

                # 处理 gzip 压缩
                try:
                    content = gzip.decompress(content)
                except (gzip.BadGzipFile, OSError):
                    # 内容未被 gzip 压缩，直接使用原始内容
                    pass

                data = content.decode('utf-8')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(data)
                json_path = temp_path
                print("JSON下载完成")
            except Exception as e:
                print(f"下载JSON失败: {e}")
                return 1
        elif reuse_existing_extract_if_complete(args.output, json_path, screenshot_url,
                                                force_refresh=args.force_refresh):
            return 0
    else:
        print("请提供JSON文件路径或使用--url参数指定蓝湖项目URL")
        print("示例:")
        print("  python lanhu_parser.py sketch_data.json")
        print("  python lanhu_parser.py https://alipic.lanhuapp.com/FigmaJSONxxx.json")
        print("  python lanhu_parser.py --url 'https://lanhuapp.com/web/#/item/project/stage?tid=xxx&pid=xxx' --list")
        print("  python lanhu_parser.py --url 'https://lanhuapp.com...' --design '首页'")
        return 1

    # ===== 检测 JSON 格式 =====
    json_format = args.format
    if json_format == 'auto':
        json_format = detect_json_format(json_path)
        print(f"检测到 JSON 格式: {json_format.upper()}")

    # ===== 根据格式选择解析器 =====
    # original_url 在 --json-path URL 模式下有值，其他模式为 None
    if json_format == 'figma':
        parser_instance = FigmaJsonParser(json_path, args.output, original_url=original_url)
    else:
        parser_instance = LanhuSketchParser(json_path, args.output, original_url=original_url)

    # 执行解析
    if not parser_instance.parse():
        print("解析失败")
        return 1

    parser_instance.output_dir.mkdir(parents=True, exist_ok=True)
    persist_source_json(
        parser_instance.output_dir,
        json_path,
        original_url=original_url,
        design_id=getattr(parser_instance, "design_id", None),
    )

    if not args.no_download:
        parser_instance.download_slices()
        sync_annotation_slice_status(parser_instance)

    # 使用紧凑格式输出（优化 AI 读取效率）。必须在切图下载后写入，保证状态一致。
    parser_instance.save_outputs_compact()

    # 下载页面截图
    screenshot_local_path = None
    if screenshot_url:
        screenshot_local_path = parser_instance.download_screenshot(screenshot_url)
    else:
        existing_screenshot = parser_instance.output_dir / "screenshot.png"
        if existing_screenshot.exists():
            screenshot_local_path = str(existing_screenshot)

    save_layout_analysis_file(parser_instance, screenshot_local_path)

    # 验证结构化标注
    if args.validate:
        validation_issues = parser_instance.validate_structure()
        if validation_issues:
            print("\n=== 验证问题 ===")
            for issue in validation_issues:
                print(f"  [{issue['type']}] {issue['layer']}: {issue['description']}")
            parser_instance.issues.extend([IssueItem(**i) for i in validation_issues])
            save_issues_file(parser_instance.output_dir, parser_instance.issues)
        else:
            print("\n验证通过，未发现问题")

    print("\n=== 解析摘要 ===")
    if json_format == 'figma':
        print(f"画板: {parser_instance.artboard_name}")
        print(f"格式: Figma JSON")
    else:
        print(f"画板数量: {len(parser_instance.artboards)}")
        print(f"格式: Sketch JSON")
    print(f"切图数量: {len(parser_instance.slices)}")
    print(f"阻塞问题: {len(parser_instance.issues)}")
    print(f"design_id: {getattr(parser_instance, 'design_id', '')}")
    print(f"extract_dir: {parser_instance.output_dir}")
    if original_url:
        print(f"source_url: {original_url}")

    return 0


if __name__ == '__main__':
    exit(main())
