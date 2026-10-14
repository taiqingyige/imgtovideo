import os
import re
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import tempfile
import shutil

class VideoMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片转视频工具 (强制9:16版)")
        self.root.geometry("650x480")
        self.root.resizable(False, False)

        self.folder_path = tk.StringVar()
        self.bgm_path = tk.StringVar()
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self.root, text="1. 选择图片所在文件夹:", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        frame1 = tk.Frame(self.root)
        frame1.pack(fill="x", padx=10)
        tk.Entry(frame1, textvariable=self.folder_path, state="readonly").pack(side="left", fill="x", expand=True)
        tk.Button(frame1, text="浏览...", command=self.select_folder).pack(side="right", padx=(5, 0))

        tk.Label(self.root, text="2. 选择背景音乐 (可选):", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        frame2 = tk.Frame(self.root)
        frame2.pack(fill="x", padx=10)
        tk.Entry(frame2, textvariable=self.bgm_path, state="readonly").pack(side="left", fill="x", expand=True)
        tk.Button(frame2, text="浏览...", command=self.select_bgm).pack(side="right", padx=(5, 0))

        info_text = "⚙️ 强制模式：所有图片统一转为 1080x1920 (9:16) | 自动黑边填充"
        tk.Label(self.root, text=info_text, fg="gray", font=("Arial", 10)).pack(anchor="w", padx=10, pady=(15, 5))

        self.log_text = scrolledtext.ScrolledText(self.root, height=12, state="disabled", font=("Courier", 12))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

        self.start_btn = tk.Button(self.root, text="🎬 开始生成 9:16 视频", bg="#4CAF50", fg="white", 
                                   font=("Arial", 14, "bold"), command=self.start_processing)
        self.start_btn.pack(fill="x", padx=10, pady=10)

    def log(self, msg):
        def _update():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        self.root.after(0, _update)

    def select_folder(self):
        path = filedialog.askdirectory(title="选择包含图片的文件夹")
        if path:
            self.folder_path.set(path)

    def select_bgm(self):
        path = filedialog.askopenfilename(
            title="选择背景音乐",
            filetypes=[("Audio Files", "*.mp3 *.wav *.m4a *.aac *.flac"), ("All Files", "*.*")]
        )
        if path:
            self.bgm_path.set(path)

    def natural_sort_key(self, s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split('([0-9]+)', s)]

    def process(self):
        temp_dir = None
        temp_wav = None
        try:
            folder = self.folder_path.get()
            bgm = self.bgm_path.get()
            
            # 支持更多图片格式
            imgs = sorted(
                [f for f in os.listdir(folder) if f.lower().endswith(('.png','.jpg','.jpeg','.bmp','.webp'))], 
                key=self.natural_sort_key
            )
            
            if not imgs:
                self.log("❌ 错误：所选文件夹内没有找到图片！")
                return

            self.log(f"📂 找到 {len(imgs)} 张图片")
            self.log("📐 目标规格：强制 9:16 (1080x1920)")

            total_duration = len(imgs) * 1
            folder_name = os.path.basename(folder)
            output_video = os.path.join(folder, f"{folder_name}_9x16.mp4")

            # --- 步骤1: 创建临时目录并标准化图片序列 ---
            self.log("⏳ 步骤1/3: 正在将所有图片转换为 1080x1920 PNG...")
            temp_dir = tempfile.mkdtemp()
            
            # 核心滤镜：等比缩放至适合 1080x1920，不足部分用黑色填充
            # force_original_aspect_ratio=decrease 保证图片完整显示
            # pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black 保证居中且背景为黑
            target_vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"

            for i, img in enumerate(imgs):
                src = os.path.join(folder, img)
                dst = os.path.join(temp_dir, f"{i+1:03d}.png")
                
                cmd_convert = [
                    'ffmpeg', '-y', '-i', src,
                    '-vf', target_vf,
                    '-q:v', '1',  # 最高质量
                    dst
                ]
                # 静默执行，出错再捕获
                result = subprocess.run(cmd_convert, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if result.returncode != 0:
                    self.log(f"⚠️ 警告：图片 '{img}' 转换失败，已跳过。")
                    continue
            
            # 检查是否还有有效图片
            processed_imgs = [f for f in os.listdir(temp_dir) if f.endswith('.png')]
            if not processed_imgs:
                self.log("❌ 错误：没有成功转换任何图片。")
                return
                
            self.log(f"✅ 成功标准化 {len(processed_imgs)} 张图片")

            # --- 步骤2: 使用 image2 模式合成无声视频 ---
            self.log("⏳ 步骤2/3: 正在合成 9:16 无声视频...")
            temp_video = os.path.join(temp_dir, "video_only.mp4")
            
            cmd_video = [
                'ffmpeg', '-y',
                '-framerate', '1',  # 每张图持续1秒
                '-i', os.path.join(temp_dir, "%03d.png"),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-r', '30',
                '-preset', 'fast',
                '-an',
                temp_video
            ]
            
            result_video = subprocess.run(cmd_video, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result_video.returncode != 0:
                self.log(f"❌ 视频合成失败:\n{result_video.stderr[-500:]}")
                return
            
            self.log("✅ 无声视频生成成功")

            # --- 步骤3: 处理音频并合并 ---
            has_bgm = False
            if bgm and os.path.exists(bgm):
                self.log("🎵 步骤3/3: 正在处理背景音乐...")
                try:
                    fd, temp_wav = tempfile.mkstemp(suffix=".wav")
                    os.close(fd)
                    
                    convert_cmd = [
                        'ffmpeg', '-y', '-i', bgm, 
                        '-t', str(total_duration),
                        '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                        temp_wav
                    ]
                    subprocess.run(convert_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                    has_bgm = True
                except Exception as e:
                    self.log(f"⚠️ BGM处理失败，将生成无声视频: {str(e)}")

            if has_bgm:
                self.log("🔄 正在合并视频与音频...")
                cmd_merge = [
                    'ffmpeg', '-y',
                    '-i', temp_video,
                    '-i', temp_wav,
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-shortest',
                    output_video
                ]
                result_merge = subprocess.run(cmd_merge, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                if result_merge.returncode == 0:
                    self.log(f"✅ 成功！9:16 视频已保存至:\n{output_video}")
                    self.root.after(0, lambda: messagebox.showinfo("完成", "视频生成成功！"))
                else:
                    self.log(f"❌ 合并失败:\n{result_merge.stderr[-500:]}")
            else:
                shutil.move(temp_video, output_video)
                self.log(f"✅ 成功！9:16 无声视频已保存至:\n{output_video}")
                self.root.after(0, lambda: messagebox.showinfo("完成", "视频生成成功！"))
                
        except FileNotFoundError:
            self.log("❌ 找不到 ffmpeg！请确保已安装 (brew install ffmpeg)")
            self.root.after(0, lambda: messagebox.showerror("环境缺失", "未找到 ffmpeg！"))
        except Exception as e:
            self.log(f"❌ 发生未预期的错误: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
        finally:
            # 清理临时目录
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
            # 清理临时音频
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except:
                    pass
            
            self.root.after(0, lambda: self.start_btn.config(state="normal", text="🎬 开始生成 9:16 视频"))

    def start_processing(self):
        if not self.folder_path.get():
            messagebox.showwarning("提示", "请先选择图片文件夹！")
            return
        
        self.start_btn.config(state="disabled", text="处理中...请勿关闭")
        
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        
        threading.Thread(target=self.process, daemon=True).start()

if __name__ == "__main__":
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except FileNotFoundError:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("环境缺失", "未检测到 ffmpeg！\n请在终端运行: brew install ffmpeg")
        exit(1)

    root = tk.Tk()
    app = VideoMakerApp(root)
    root.mainloop()