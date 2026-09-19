# Danh sách tính năng giao diện GCS và công dụng

Đối chiếu với mã nguồn `e05fc1d` (19/09/2026), cộng phần đọc lỗi đỏ thành tiếng làm tối 19/09. Phần phân tích chi tiết và số đo xem ở [`BAO_CAO_GIAO_DIEN_chi_tiet.md`](BAO_CAO_GIAO_DIEN_chi_tiet.md) (cột "Mục").

Ứng dụng có 7 tab: **Bay** (màn cảm ứng), **Trạng thái**, **Điều khiển**, **Thông báo**, **Camera**, **Phân tích** và **Cài đặt**. Ngoài ra còn banner chế độ ở đỉnh cửa sổ, dock chọn nguồn bên phải và widget trạng thái đường truyền ở góc dưới phải.

---

## 1. Kết nối

| # | Tính năng | Công dụng | Mục |
|---|---|---|---|
| 1 | Chọn profile nguồn (REAL / SIM / REPLAY) | Chọn bay thật, bay mô phỏng hay xem lại chuyến cũ. Mở app lên **không tự kết nối**, nên không có chuyện lỡ nối vào drone thật | 4.1 |
| 2 | Dock chọn nguồn bên phải | Là chỗ kết nối/ngắt **duy nhất**. Chỉ có một chỗ nên không bấm nhầm được | 4.12 |
| 3 | Tự quét cổng USB | Cắm radio SiK hay bộ điều khiển bay vào là thấy ngay trong danh sách, baud tự chọn đúng, không phải sửa file cấu hình. Thiếu quyền `dialout` thì app in sẵn lệnh cần chạy | 4.1 |
| 4 | Tự nối lại khi rút rồi cắm lại USB | Lỏng cáp giữa buổi bay thì cắm lại là app tự nối, kể cả khi tên cổng đổi. App nhận thiết bị theo số serial nên không nối nhầm sang radio khác | 4.14 |
| 5 | Hai nguồn dữ liệu song song (MAVLink + ROS 2) | Mất một nguồn vẫn còn nguồn kia. Mỗi con số trên màn hình luôn lấy từ nguồn tươi nhất | 2.1 |
| 6 | Banner chế độ 7 trạng thái | Liếc một cái là biết đang ở đâu: đang bay thật, mô phỏng hay phát lại, đang chờ dữ liệu, mất ROS 2 (mất tầm nhìn) hay mất MAVLink (mất quyền điều khiển) | 4.2 |
| 7 | Widget trạng thái đường truyền | Thấy băng thông thực và % mất gói của từng đường. Biết sóng yếu **trước** khi mất hẳn | 4.8 |
| 8 | Mô phỏng đứt truyền (chỉ ở SIM) | Tập xử lý tình huống mất sóng trên mô phỏng mà không phải rút dây. Khi bay thật thì dock này bị ẩn | 4.9, 8.2 |
| 9 | Phát lại `.tlog` | Xem lại một chuyến bay cũ có tua và tạm dừng. Mọi nút lệnh đều bị khoá để không gửi nhầm lệnh | 4.9 |
| 10 | Tự ghi `.tlog` ở mọi chế độ | Có bằng chứng để tra lại sau sự cố. Mở lại được bằng Mission Planner | 9 |

## 2. Màn bay (tab Bay — cảm ứng kiểu DJI)

| # | Tính năng | Công dụng | Mục |
|---|---|---|---|
| 11 | Bố cục cảm ứng, nút ≥ 46 px, tự co giãn | Bấm được bằng ngón tay ngoài bãi bay. Cùng một màn hình chạy được trên laptop lẫn máy tính bảng | 4.12 |
| 12 | Xác nhận mọi lệnh bằng thanh trượt | Chạm nhầm không gửi được lệnh: phải kéo hết thanh thì lệnh mới đi. Bảng xác nhận tự đóng sau 15 s hoặc khi mất đường truyền | 4.12 |
| 13 | Nút cắt động cơ | Tắt động cơ khẩn cấp. Hậu quả ("drone RƠI TỰ DO") hiện đỏ ngay trên thanh trượt để người bấm biết mình đang làm gì | 4.12, 4.14 |
| 14 | Cất cánh có chọn độ cao | Chọn nhanh 3/5/10/20/30 m hoặc nhập 1–120 m mà không cần bàn phím ảo | 4.12 |
| 15 | Đổi chế độ bay | Chọn mode (GUIDED, AUTO, LOITER…) từ danh sách mà bộ điều khiển bay hỗ trợ | 4.12 |
| 16 | Cần ảo + nút leo/hạ | Lái tay trong GUIDED: chỉnh khung hình camera, né vật cản. Buông tay là drone dừng tại chỗ. Khi cần ảo bị khoá, app nói rõ lý do | 4.10 |
| 17 | Thanh telemetry trên đỉnh | Trả lời câu hỏi "có được bay tiếp không": trạng thái ARM, mode, GPS (đủ 3 điều kiện), pin %/V. Mỗi ô tự đổi màu vàng/đỏ | 4.4, 4.11 |
| 18 | Thanh telemetry dưới đáy | Trả lời câu hỏi "đang bay thế nào": độ cao, khoảng cách về nhà, tốc độ ngang, tốc độ lên/xuống, hướng, giờ bay | 4.4 |
| 19 | Ô **CÒN** | Cho biết còn bay được bao nhiêu phút trước mốc failsafe pin, tính theo dòng điện đang ăn | 4.14 |
| 20 | Dòng **SẴN SÀNG ARM** | Cho biết ARM được chưa. Nếu chưa thì kèm lý do PreArm, không phải đoán | 4.14 |
| 21 | Cảnh báo đứng yên | Phát hiện cấu hình nguy hiểm trước khi bay: failsafe đang tắt, ngưỡng pin sai, pin không đầy. Khi đang bay thì báo **VỀ NHÀ NGAY** nếu pin chỉ còn vừa đủ để RTL | 4.14 |
| 22 | Dòng lỗi nổi | Lỗi và cảnh báo từ bộ điều khiển bay tự hiện lên màn bay, không phải mở tab khác để đọc. Chạm vào dòng lỗi là mở tab Thông báo ngay đúng dòng đó | 4.11, 4.14 |
| 23 | Dòng lệch hai nguồn | Báo đỏ khi vị trí từ MAVLink và từ ROS 2 lệch nhau quá 5 m, tức là có một nguồn đang sai | 4.4, 5.3 |
| 24 | La bàn + chân trời nhân tạo | Cho biết drone đang quay mặt về đâu và có đang nghiêng không | 4.4 |
| 25 | Đổi chỗ camera ↔ bản đồ | Chạm ô nhỏ để xem camera toàn màn mà bản đồ vẫn còn ở góc. Ngắt kết nối thì bản đồ tự trở về màn lớn | 4.13 |

## 3. Bản đồ

| # | Tính năng | Công dụng | Mục |
|---|---|---|---|
| 26 | Ảnh vệ tinh ngoại tuyến (tới zoom 21) | Có bản đồ nét ngoài bãi bay dù không có mạng. Khi có mạng thì app tải bù phần còn thiếu | 2.4, 4.3 |
| 27 | Bám theo drone | Drone luôn ở giữa màn hình. Kéo bản đồ để xem chỗ khác thì chế độ bám tự tắt | 4.3 |
| 28 | Chạm đúp | Đưa tâm về drone và phóng tới zoom 20 chỉ bằng một thao tác | 4.14 |
| 29 | Tam giác chỉ hướng mũi | Thấy ngay drone đang quay mặt về đâu. Chưa biết hướng thì vẽ hình tròn, không đoán | 4.11 |
| 30 | Vệt bay | Thấy quãng đường drone đã đi (tối đa 3 000 điểm) | 4.3 |
| 31 | Điểm home | Biết drone sẽ bay về đâu khi RTL. Nếu home chỉ là đoán thì dải chữ dưới bản đồ nói rõ | 4.3 |
| 32 | Hàng rào geofence | Thấy vùng được phép bay và khoảng cách tới rào gần nhất. Chỉ vẽ những rào đang thật sự bật | 4.3, 4.11 |

## 4. Đường bay waypoint

| # | Tính năng | Công dụng | Mục |
|---|---|---|---|
| 33 | Giữ 2 s để đặt điểm | Dựng đường bay bằng tay trên bản đồ. Phải giữ 2 s nên chạm nhầm không thành một điểm | 6.1, 4.14 |
| 34 | Chọn độ cao điểm | Có 6 mức nhanh hoặc ô nhập 1–120 m. Giá trị bị kẹp trong giới hạn an toàn | 6.1 |
| 35 | Nạp lên bộ điều khiển bay | Gửi đường bay xuống drone. App tự chèn home, TAKEOFF và LAND, nên chuyến AUTO cất cánh và hạ cánh đúng | 6.1–6.2 |
| 36 | Đọc ngược sau khi nạp | Bản đồ vẽ đúng đường bay mà drone **đang giữ**, không phải cái vừa gửi đi | 6.1 |
| 37 | Bay tới điểm | Cho drone bay thẳng tới một điểm chạm trên bản đồ, giữ độ cao đã chọn | 4.3 |
| 38 | Xoá đường bay trên bộ điều khiển bay | Huỷ nhiệm vụ đang nạp | 4.3 |

## 5. Lệnh và an toàn

| # | Tính năng | Công dụng | Mục |
|---|---|---|---|
| 39 | Chốt ARM theo cần ga | Không cho ARM khi cần ga đang cao, tránh drone vọt lên ngay lúc ARM | 4.6 |
| 40 | Chốt TAKEOFF | Chặn lệnh cất cánh khi không ở GUIDED hoặc chưa ARM và nói rõ lý do. Sau 6 s app kiểm lại xem drone có thật sự lên không | 4.6, 4.14 |
| 41 | Nút khẩn cấp RTL / LAND / DISARM | Luôn gửi được lệnh cứu drone: đi thẳng qua MAVLink, không qua bước kiểm tra nào | 2.3, 4.6 |
| 42 | DISARM hai bậc | Drone dưới đất thì tắt được ngay. Đang bay thì phải bấm lại để xác nhận, nên một cú bấm nhầm không làm rơi drone | 4.6 |
| 43 | Hạn chờ phản hồi 3 s | Không có phản hồi thì app báo "KHÔNG CÓ PHẢN HỒI". Im lặng không bao giờ bị coi là thành công | 4.7 |
| 44 | Ghi vết lệnh ở ba nơi | Tra lại được mọi lệnh đã bấm cùng kết quả: thanh trạng thái, tab Thông báo và `logs/commands.log` | 4.7 |
| 45 | Laptop cầm toàn quyền | Node trên máy tính nhúng không lái được drone. Mọi lệnh chỉ đi từ laptop | 2.3 |
| 46 | Chặn đóng cửa sổ khi đang ARM | Tránh đóng nhầm app lúc cánh quạt đang quay: phải bấm đóng lần hai trong 3 s | 4.11 |
| 47 | Đọc cảnh báo thành tiếng | Nghe được cảnh báo mà không phải nhìn màn hình ("Sẵn sàng arm", "Mất tín hiệu", "Về nhà ngay"…), kể cả **mọi dòng lỗi đỏ** của bộ điều khiển bay (trừ PreArm), lúc ARM/DISARM và lúc đổi mode. Đọc chậm, giọng nữ. Có cả tiếng Việt và tiếng Anh | 4.14 |

## 6. Các tab khác

| # | Tab | Tính năng | Công dụng | Mục |
|---|---|---|---|---|
| 48 | Trạng thái | Bảng mọi trường MAVLink | Tra bất kỳ con số nào drone gửi lên, có ô lọc và nút tạm dừng. Dữ liệu đã cũ thì chuyển xám | 4.5, 5.1 |
| 49 | Trạng thái | `SENSOR.*` giải mã | Biết ngay cảm biến nào đang hỏng | 4.5 |
| 50 | Trạng thái | Cột Giải thích | Mỗi hàng có một dòng giải thích ngay trong bảng, theo ngôn ngữ đang chọn: 1 036/1 037 tham số FC thật và 328/328 trường telemetry có tiếng Việt; tooltip kèm ý nghĩa các giá trị | 4.5, 4.11 |
| 51 | Điều khiển | Lệnh thường + trạng thái node ROS 2 | ARM, đổi mode, cất cánh bằng chuột. Thấy node nào đang chạy trên máy tính nhúng | 4.6 |
| 52 | Điều khiển | Khối trạng thái bay | Xem SẴN SÀNG ARM, CÒN và các cảnh báo mà không phải quay sang màn bay | 4.14 |
| 53 | Thông báo | Dòng thời gian thông báo | Đọc lại toàn bộ lỗi và kết quả lệnh, có lọc theo mức. Số cảnh báo chưa đọc hiện ngay trên tên tab | 4.7, 4.11 |
| 54 | Camera | Luồng MJPEG từ máy tính nhúng | Xem camera toàn khung. Mất tín hiệu thì hiện ô xám, không đứng hình khung cũ | 7 |
| 55 | Camera | Địa chỉ video riêng cho profile | Bay mô phỏng mà vẫn xem được camera thật trên Pi | 7.1, 4.14 |
| 56 | Phân tích | Đọc log `.tlog`/`.bin`, kéo log từ thẻ SD | Xem lại chuyến vừa bay ngay tại bãi, không cần rút thẻ nhớ | 4.11 |
| 57 | Phân tích | Đồ thị + quỹ đạo 3D | Tối đa 4 đồ thị, chuẩn hoá 0–1 để so hình dạng, quỹ đạo bay 3D, chế độ trực tiếp giữ 60 s | 4.11 |
| 58 | Cài đặt | Song ngữ Việt ↔ Anh | Đổi ngôn ngữ ngay khi đang chạy, không mất kết nối | 4.11 |
| 59 | Cài đặt | Bật/tắt giọng nói | Tắt tiếng khi không cần | 4.14 |
