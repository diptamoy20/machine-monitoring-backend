# Factory Automation Cheat Sheet: Video Analytics Setup
**Project Workspace Target:** `factory_analytics/`
**Target Framework:** Python + OpenCV + YOLOv8/v11 Classification

---

## 📋 Section 1: Preprocessing & Training Pipeline (Quick Notes)

### Phase 1: Local Setup
1. **Create Root Folder:** Create a base folder named `factory_analytics`.
2. **Save Script:** save code into a file named `preprocess.py` inside that folder.
3. **Generate Paths:** Run `python preprocess.py` once via terminal to auto-create the necessary paths.
4. **Sort Samples:** Drop raw videos into `raw_videos/running/` or `raw_videos/stopped/`.

### Phase 2: Preprocessing Data
5. **Set Categories:** Ensure `CLASSES = ["running", "stopped"]` is configured in `preprocess.py`.
6. **Slice Videos:** Run `python preprocess.py` again to chop videos into image frame files.
7. **Verify Folders:** Check `processed_dataset/` for $224 \times 224$ px images sorted into `train/` and `val/`.

### Phase 3: Model Training
8. **Save Trainer:** save training code block into a text file named `train.py`.
9. **Run Training:** Execute `python train.py` in your system terminal.
10. **Monitor Loop:** Watch training metrics; target `top1_acc` values climbing near `1.0`.

### Phase 4: Model Quality Verification
11. **Check Matrix:** Review `confusion_matrix.png` to confirm clean diagonal blocks (target: `1.00`).
12. **Locate Brain:** Verify that your optimized network weights file saved to `weights/best.pt`.
13. **Save Tester:** save verification display logic into a script named `verify_model.py`.
14. **Test Video:** Run `python verify_model.py` to see live status boxes overlaying unseen test clips.

---

