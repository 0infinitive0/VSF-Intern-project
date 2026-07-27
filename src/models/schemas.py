from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn từ user")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Phản hồi từ agent")
    analysis: str = Field(default="", description="Phân tích nội bộ")

class AttractionPayload(BaseModel):
    attraction_id: str = Field(..., description="UUID from PostgreSQL")
    name: str = Field(..., description="Tên điểm tham quan hoặc Tour")
    destination_id: str = Field(..., description="UUID trỏ về điểm đến")
    category: str = Field(..., description="Phân loại (e.g., Tour, Biển)")
    is_tour: bool = Field(default=False)
    ticket_price_range: str | None = Field(default=None, description="Mức giá")


class HotelPayload(BaseModel):
    hotel_id: str = Field(..., description="UUID từ bảng hotels")
    name: str = Field(..., description="Tên khách sạn")
    destination_id: str | None = Field(default=None, description="UUID trỏ về điểm đến")
    star_rating: float | None = Field(default=None, description="Hạng sao")
    price_tier: str | None = Field(default=None, description="Mức giá")
    amenities: list[str] | None = Field(default=None, description="Danh sách tiện ích")


class RoomPayload(BaseModel):
    room_id: str = Field(..., description="UUID từ bảng rooms")
    hotel_id: str = Field(..., description="UUID trỏ về bảng hotels")
    name: str = Field(..., description="Tên phòng")
    max_guests: int | None = Field(default=None, description="Số khách tối đa")
    room_size_sqm: float | None = Field(default=None, description="Diện tích phòng")
    view: str | None = Field(default=None, description="Hướng nhìn")
