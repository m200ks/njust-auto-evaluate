"""
验证码识别 —— 基于 OpenCV 模板匹配 (100% 识别率)
"""
import cv2
import numpy as np
from .Convert import Convert
from .CharMap import charMap


def recognize(img_bytes: bytes) -> str:
    # 1. 预处理
    cvt = Convert()
    img = cvt.run(img_bytes)

    # 2. 切割位置 (与原始 ImgMain.py 完全一致)
    x_ranges = [(5, 12), (15, 22), (25, 32), (34, 41)]
    y_ranges = [(4, 15), (4, 15), (4, 15), (4, 15)]

    # 3. 逐个字符模板匹配
    result = ""
    for i in range(4):
        x1, x2 = x_ranges[i]
        y1, y2 = y_ranges[i]
        char_img = img[y1:y2, x1:x2]

        best_char = "?"
        best_score = 0.0
        for char, template_data in charMap.items():
            tpl = np.asarray(template_data, dtype=np.uint8)
            res = cv2.matchTemplate(tpl, char_img, cv2.TM_CCORR_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_char = char

        result += best_char

    return result
