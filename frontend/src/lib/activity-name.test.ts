import { describe, expect, it } from 'vitest'
import { placeNameFromActivity } from './activity-name'

describe('placeNameFromActivity', () => {
  it('strips the meal lead-in to leave just the venue name', () => {
    expect(placeNameFromActivity('Ăn trưa tại NHÀ HÀNG NGON')).toBe('NHÀ HÀNG NGON')
    expect(placeNameFromActivity('Ăn sáng tại Khách sạn ABC')).toBe('Khách sạn ABC')
    expect(placeNameFromActivity('Ăn tối tại Nhà hàng Biển')).toBe('Nhà hàng Biển')
  })

  it('strips the covered-meal / hotel-category variants', () => {
    expect(placeNameFromActivity('Ăn sáng đã bao gồm tại Khách sạn ABC')).toBe('Khách sạn ABC')
    expect(placeNameFromActivity('Ăn trưa đã bao gồm và nghỉ ngơi tại Khách sạn ABC')).toBe('Khách sạn ABC')
    expect(placeNameFromActivity('Ăn trưa và nghỉ ngơi tại Khách sạn ABC')).toBe('Khách sạn ABC')
    expect(placeNameFromActivity('Ăn tối đã bao gồm tại Khách sạn ABC')).toBe('Khách sạn ABC')
  })

  it('strips the coffee/rest/evening/attraction templates', () => {
    expect(placeNameFromActivity('Thư giãn tại Cafe Cộng')).toBe('Cafe Cộng')
    expect(placeNameFromActivity('Nghỉ ngơi tại Khách sạn ABC')).toBe('Khách sạn ABC')
    expect(placeNameFromActivity('Dạo chơi tại Phố cổ Hội An')).toBe('Phố cổ Hội An')
    expect(placeNameFromActivity('Tham quan Bà Nà Hills')).toBe('Bà Nà Hills')
  })

  it('strips the free-exploration fallback', () => {
    expect(placeNameFromActivity('Tự do khám phá khu vực quanh Khách sạn ABC')).toBe('Khách sạn ABC')
  })

  it('falls back to the full string when no known template matches', () => {
    expect(placeNameFromActivity('Một hoạt động lạ không theo mẫu nào')).toBe(
      'Một hoạt động lạ không theo mẫu nào',
    )
  })
})
