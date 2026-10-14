import os
import re
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import tempfile
import shutil
from multiprocessing import Pool, cpu_count

# --- 核心处理逻辑 (修复音频缺失问题) ---
def process_single_folder(args):
    """
    处理单个子文件夹的任务函数
    args: (folder_path, bgm_path, target_res)
    """
    folder_path, bgm_path, target_res = args
    folder_name = os.path.basename(folder_path)
    out_w, out_h = target_res
    temp_dir = None
    temp_wav = None
    
    try:
        # 1. 获取图片列表 (自然排序)
        all_files = os.listdir(folder_path)
        imgs = sorted(
            [f for f in all_files if f.lower().endswith(('.png','.jpg','.jpeg','.bmp','.webp'))], 
            key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split('([0-9]+)', s)]
        )
        
        if not imgs:
            return (folder_name, False, "文件夹内无图片，跳过")

        total_duration = len(imgs) * 1 # 假设每张图1秒
        output_video = os.path.join(os.path.dirname(folder_path), f"{folder_name}.mp4")

        # 2. 标准化图片序列 (9:16 + 黑边)
        temp_dir = tempfile.mkdtemp()
        target_vf = f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
        
        valid_count = 0
        for i, img in enumerate(imgs):
            src = os.path.join(folder_path, img)
            dst = os.path.join(temp_dir, f"{valid_count+1:03d}.png")
            
            cmd_convert = [
                'ffmpeg', '-y', '-i', src,
                '-vf', target_vf,
                '-q:v', '1',
                dst
            ]
            result = subprocess.run(cmd_convert, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                valid_count += 1
        
        if valid_count == 0:
            return (folder_name, False, "没有成功转换任何图片")

        # 3. 合成无声视频
        temp_video = os.path.join(temp_dir, "video_only.mp4")
        
        cmd_video = [
            'ffmpeg', '-y',
            '-framerate', '1',
            '-i', os.path.join(temp_dir, "%03d.png"),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-preset', 'fast',
            '-an',
            temp_video
        ]
        
        result_video = subprocess.run(cmd_video, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result_video.returncode != 0:
            return (folder_name, False, "FFmpeg 视频合成错误")
        
        # 4. 处理音频并合并 (增强版)
        has_bgm = False
        if bgm_path and os.path.exists(bgm_path):
            try:
                fd, temp_wav = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                
                # 【修复点1】更稳健的音频转换命令
                convert_cmd = [
                    'ffmpeg', '-y', '-i', bgm_path, 
                    '-t', str(total_duration),
                    '-acodec', 'pcm_s16le', 
                    '-ar', '44100', 
                    '-ac', '2',
                    '-f', 'wav',  # 强制输出格式为 wav
                    temp_wav
                ]
                result_convert = subprocess.run(convert_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                
                # 【修复点2】验证生成的 WAV 文件是否有效
                if os.path.getsize(temp_wav) < 100: # 如果文件太小，说明转换失败
                    raise Exception("WAV file too small")
                    
                has_bgm = True
            except Exception as e:
                # 如果音频处理失败，记录但不中断，后面会生成无声视频
                pass 

        if has_bgm:
            # 【修复点3】显式映射视频流和音频流
            cmd_merge = [
                'ffmpeg', '-y',
                '-i', temp_video,
                '-i', temp_wav,
                '-map', '0:v:0',  # 明确使用第一个输入的视频流
                '-map', '1:a:0',  # 明确使用第二个输入的音频流
                '-c:v', 'copy',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                output_video
            ]
            result_merge = subprocess.run(cmd_merge, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if result_merge.returncode != 0:
                # 合并失败至少保留无声视频
                shutil.move(temp_video, output_video)
                return (folder_name, True, f"生成成功 (音频合并异常，已保存无声版)")
        else:
            # 无音频，直接移动
            shutil.move(temp_video, output_video)
            
        return (folder_name, True, f"成功生成: {output_video}")

    except Exception as e:
        return (folder_name, False, f"处理异常: {str(e)}")
    finally:
        # 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        if temp_wav and os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except:
                pass

# --- GUI 界面部分 ---
class BatchVideoMakerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("批量图片转视频 (修复音频版·多进程)")
        self.root.geometry("750x550")
        self.root.resizable(False, False)

        self.root_path = tk.StringVar()
        self.bgm_path = tk.StringVar()
        self.setup_ui()

    def setup_ui(self):
        # 1. 选择根目录
        tk.Label(self.root, text="1. 选择根目录 (内含多个子文件夹):", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        frame1 = tk.Frame(self.root)
        frame1.pack(fill="x", padx=10)
        tk.Entry(frame1, textvariable=self.root_path, state="readonly").pack(side="left", fill="x", expand=True)
        tk.Button(frame1, text="浏览...", command=self.select_root).pack(side="right", padx=(5, 0))

        # 2. 选择统一背景音乐
        tk.Label(self.root, text="2. 选择统一背景音乐 (可选):", font=("Arial", 12)).pack(anchor="w", padx=10, pady=(10, 0))
        frame2 = tk.Frame(self.root)
        frame2.pack(fill="x", padx=10)
        tk.Entry(frame2, textvariable=self.bgm_path, state="readonly").pack(side="left", fill="x", expand=True)
        tk.Button(frame2, text="选择音频...", command=self.select_bgm).pack(side="right", padx=(5, 0))

        # 提示信息
        info_frame = tk.Frame(self.root)
        info_frame.pack(fill="x", padx=10, pady=(15, 5))
        tk.Label(info_frame, text="⚡ 多核并行 | 所有视频将使用同一首BGM", fg="#2196F3", font=("Arial", 10)).pack(side="left")
        tk.Label(info_frame, text="📐 强制 9:16 (1080x1920)", fg="gray", font=("Arial", 10)).pack(side="right")

        # 日志区域
        self.log_text = scrolledtext.ScrolledText(self.root, height=18, state="disabled", font=("Courier", 11))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

        # 开始按钮
        self.start_btn = tk.Button(self.root, text="🚀 开始批量生成", bg="#2196F3", fg="white", 
                                   font=("Arial", 14, "bold"), command=self.start_batch_processing)
        self.start_btn.pack(fill="x", padx=10, pady=10)

    def log(self, msg):
        def _update():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        self.root.after(0, _update)

    def select_root(self):
        path = filedialog.askdirectory(title="选择根目录 (内含多个子文件夹)")
        if path:
            self.root_path.set(path)

    def select_bgm(self):
        path = filedialog.askopenfilename(
            title="选择背景音乐",
            filetypes=[("Audio Files", "*.mp3 *.wav *.m4a *.aac *.flac"), ("All Files", "*.*")]
        )
        if path:
            self.bgm_path.set(path)

    def start_batch_processing(self):
        root_dir = self.root_path.get()
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showwarning("提示", "请先选择一个有效的根目录！")
            return

        # 扫描子文件夹
        sub_folders = [
            os.path.join(root_dir, d) for d in os.listdir(root_dir) 
            if os.path.isdir(os.path.join(root_dir, d))
        ]

        if not sub_folders:
            messagebox.showwarning("提示", "所选目录下没有找到任何子文件夹！")
            return

        bgm = self.bgm_path.get()
        if bgm and not os.path.exists(bgm):
            messagebox.showerror("错误", "选择的背景音乐文件不存在！")
            return

        self.log(f"📂 发现 {len(sub_folders)} 个子文件夹任务")
        if bgm:
            self.log(f"🎵 已加载统一背景音乐: {os.path.basename(bgm)}")
        else:
            self.log(f"ℹ️ 未选择背景音乐，将生成无声视频")
            
        self.log(f"💻 检测到 {cpu_count()} 个 CPU 核心，正在启动并行处理...\n")
        
        self.start_btn.config(state="disabled", text="处理中...请勿关闭")
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")

        # 准备参数列表
        task_args = [(folder, bgm, (1080, 1920)) for folder in sub_folders]

        # 在后台线程中启动多进程池
        threading.Thread(target=self.run_pool, args=(task_args,), daemon=True).start()

    def run_pool(self, task_args):
        try:
            with Pool(processes=cpu_count()) as pool:
                results = pool.map(process_single_folder, task_args)
            
            success_count = 0
            fail_count = 0
            for name, success, msg in results:
                if success:
                    self.log(f"✅ [{name}] {msg}")
                    success_count += 1
                else:
                    self.log(f"❌ [{name}] {msg}")
                    fail_count += 1
            
            self.log("-" * 40)
            self.log(f"🏁 全部完成！成功: {success_count}, 失败: {fail_count}")
            self.root.after(0, lambda: messagebox.showinfo("完成", f"批量处理结束\n成功: {success_count}\n失败: {fail_count}"))

        except Exception as e:
            self.log(f"❌ 批量处理发生严重错误: {str(e)}")
        finally:
            self.root.after(0, lambda: self.start_btn.config(state="normal", text="🚀 开始批量生成"))

if __name__ == "__main__":
    # 检查 ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except FileNotFoundError:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("环境缺失", "未检测到 ffmpeg！\n请在终端运行: brew install ffmpeg")
        exit(1)

    root = tk.Tk()
    app = BatchVideoMakerApp(root)
    root.mainloop()
