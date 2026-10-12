# Tiếp tục phiên rà lỗi ngày 04/10/2026

Tiếp nối phiên Claude `a570a089-2748-4e4f-bc7d-b04bc3c64844`, cây mã
`d2ec0a6` cùng 16 file đang sửa. Không commit trong lượt kiểm tra này.

## RAM và công cụ soak

Bài soak cũ lấy RSS trước khi Piper nạp giọng và trước khi bộ đệm trực tiếp
đầy. Đo riêng Piper: câu đầu tăng 121,7 MB, câu thứ ba tăng tổng 122,5 MB.
Đối chứng chỉ thay tổng hợp Piper bằng PCM rỗng, giữ nguyên giao diện và
telemetry: RSS 189,7 → 248,5 → 251,2 → 251,2 MB. Vì vậy mức tăng ban đầu
khoảng 184 MB không đủ để kết luận rò rỉ.

- Lượt dài trên SITL `-I1`, cổng 5773: **đủ 30 phút**. RSS 189,6 → 371,1 MB
  ở phút 1 → 373,8 MB ở phút 2, rồi giữ 373,8 MB tới phút 30. Nhận
  **1.057.037 envelope** (~587/s), **17.996 nhịp Qt** so với kỳ vọng ~18.004.
  Bản đo cũ kết thúc **FAIL, exit 1** vì so với mốc trước khởi động (+184,2 MB).
  Không thấy RSS tiếp tục tăng trong kịch bản này sau khi bộ đệm đã đầy.
- Bài đã sửa, cổng 5772: 60 giây khởi động + 2 phút đo, **PASS**, exit 0.
  RSS 373,4 → 376,1 MB (+2,8 MB), 70.451 envelope, 1.200 nhịp Qt.
- Ngưỡng tăng RSS vẫn là 60 MB. Đổi sang đồng hồ monotonic, đặt thời điểm
  kết thúc riêng để thời gian thử ngắn không bị kéo thêm một chu kỳ lấy mẫu.
- Bài sẽ FAIL nếu có khoảng lấy mẫu mất telemetry, kể cả sau đó dữ liệu về lại.
- Thêm `check_soak()` vào selfcheck: RAM khởi động ổn định được PASS; tăng
  thêm 75 MB, Qt chậm và mất telemetry đều thoát mã 1. Bản cũ bị bài kiểm
  đầu tiên bắt lỗi; bản đã sửa qua cả bốn tình huống.

Bằng chứng: `logs/soak-20261004-codex.log`,
`logs/soak-no-piper-20261004.log`, `logs/soak-fixed-20261004.log`.
Lượt dài chạy bản cũ đã được nạp vào tiến trình trước khi sửa file.

Lệnh từ nay: `python3 tools/soak.py 30 <conn> SIM` chạy **31 phút tổng cộng**,
gồm 60 giây khởi động và 30 phút đo. Kết quả này chỉ bao phủ kịch bản giao
diện nhận telemetry SITL; không phải kết luận về mọi thao tác/video/phần cứng.

## ROS2: lỗi tự ARM/cất cánh trong companion

Dựng SITL `-I2` tốc độ 1 trong terminal hiển thị trên desktop, MAVROS thật,
bridge thật, ROS domain 78 riêng, cổng SiK 5783 và WebSocket 8767. Không dùng
Gazebo/camera; bài này kiểm quyền điều khiển, telemetry và lệnh bay.

**Bản companion đang cài thất bại:** `mission_circle` đã nhận
`/gcs/authority = gcs` và in `laptop cam quyen -- dung stream setpoint`, nhưng
vẫn ARM, cất cánh tới 10 m và in `flying circle`. Các hàm dịch vụ
`set_mode`, `arm_once`/`arm`, `takeoff` chưa kiểm quyền; chỉ luồng setpoint
được chặn. Cùng dạng lỗi tồn tại trong `SimpleMission` và `FollowControl`.

Bản vá [companion-authority-20261004.patch](companion-authority-20261004.patch)
thêm kiểm quyền trước các lệnh dịch vụ và ngừng vòng thử ARM khi mất quyền.
Đã thử **trên bản sao** của ba module companion trong `/tmp`:

- Kiểm tra lệnh: bản cũ 12/26 PASS, bản vá **26/26 PASS**. Các lệnh của
  companion bị chặn khi quyền là `gcs`, vẫn gửi được khi quyền là `ros2`.
- Toàn tuyến `e2e_ros2`: **PASS**, exit 0. Hai nguồn vị trí lệch 0,00 m;
  node không tự ARM; laptop cất cánh tới 9,1 m rồi RTL và disarm.
- Bản vá **chưa áp dụng vào repo thật**
  `~/ros2-ardupilot-sitl-hardware`; đang chờ lựa chọn phạm vi sửa repo đó.
  Kết quả PASS của bản sao không có nghĩa companion đang cài đã được sửa.

Bằng chứng: `logs/e2e-ros2-20261004-before.log`,
`logs/e2e-ros2-cleanup-20261004.log`, `logs/e2e-ros2-staged-20261004.log`,
`logs/e2e-ros2-mavros-20261004.log`,
`logs/e2e-ros2-mission-staged-20261004.log`.

## Sửa công cụ e2e_ros2

- Chọn cổng bằng `--conn`/`--remote`, chạy offscreen và tắt giọng trong bài thử.
- Mỗi tiến trình con có nhóm riêng. Cleanup chỉ dừng nhóm do bài thử tạo;
  bỏ `pkill -f` vốn có thể giết mission của phiên khác.
- Khi kiểm thử thất bại trong lúc drone đang ARM, gửi RTL và chờ disarm
  trong tối đa 120 giây trước khi ngắt. Đã đo trên lỗi companion thật:
  `sau RTL: armed=False`, bài kết thúc exit 1.
- `ros2 topic echo --once` chỉ định rõ `std_msgs/msg/String`, tránh lỗi
  daemon ROS CLI `RuntimeError: !rclpy.ok()` trong lần thử đầu.
- Bắt ngoại lệ trong timer để bài thoát lỗi thay vì treo sau traceback.

## Kiểm tra chung và phần còn lại

Selfcheck cuối: **46/46 PASS**, exit 0
(`logs/selfcheck-final-20261004.log`). `git diff --check` và biên dịch ba file
Python vừa sửa đã qua. SITL gốc của Claude được giữ nguyên; stack ROS2 riêng
và daemon domain 78 đã dừng sau khi nghiệm thu bản vá trên bản sao.

Các quyết định còn lại từ phiên Claude: xác nhận trượt khi xoá đường bay
trên FC, và tự huỷ tải log khi drone chuyển sang ARM. Lượt này chưa thay đổi
hai hành vi đó. Không kiểm tra bay/phần cứng thật.
