# Discord Yapay Zeka + Moderasyon Botu (Groq)

Hem sohbet eden (varsayılan model: `openai/gpt-oss-20b`) hem de sunucuyu yöneten bot.

## Özellikler
- **Sohbet:** `@bot` ile etiketle, DM'den yaz veya `/ayar kanal` ile seçtiğin kanalda etiketsiz konuş.
- **Doğal dil moderasyonu:** Yetkili biri `@bot @Ali'yi 10 dakika sustur` yazarsa bot işlemi yapar. Hedef kişi mutlaka etiketlenmelidir. Atma, yasaklama ve mesaj silme için onay butonu çıkar. Kullanıcının kendi Discord yetkileri kontrol edilir.
- **/ komutları:** `/ban` `/unban` `/kick` `/sustur` `/sustur-kaldir` `/uyar` `/uyarilar` `/uyari-sil` `/uyari-temizle` `/temizle` `/yavas-mod` `/kilitle` `/kilidi-ac` `/sifirla` `/yardim`
- **Yönetici ayarları:** `/ayar kanal` (karşılama, görüşürüz, log, yapay zeka kanalı), `/ayar mesaj` (özel karşılama metni: `{user} {name} {server} {count}`), `/ayar otorol`, `/ayar otomod` (davet, bağlantı, spam, yasaklı kelime), `/ayar kufur`, `/ayar goster`
- **Uyarı sistemi:** Her 3. uyarıda otomatik 1 saat susturma.

## Kurulum

### 1. Discord botu
1. https://discord.com/developers/applications → uygulamanı seç → **Bot** sekmesi.
2. **Privileged Gateway Intents** altında iki tanesini de aç: **Server Members Intent** ve **Message Content Intent**.
3. **OAuth2 → URL Generator**: scope olarak `bot` ve `applications.commands`.
4. Bot izinleri: Kanalları Görüntüle, Mesaj Gönder, Mesaj Geçmişini Oku, Mesajları Yönet, Üyeleri At, Üyeleri Yasakla, Üyelere Zaman Aşımı Uygula, Kanalları Yönet, Rolleri Yönet, Bağlantı Yerleştir.
5. Botu ekle. **Sunucu ayarları → Roller** içinde bot rolünü, yönetmesini istediğin üye rollerinin **üstüne** taşı.

### 2. Groq API anahtarı
https://console.groq.com/keys

### 3. Çalıştır
```bash
pip install -r requirements.txt
cp .env.example .env     # DISCORD_TOKEN ve GROQ_API_KEY yaz
python bot.py
```

### Render
- Build Command: `pip install -r requirements.txt`
- Start Command: `python bot.py`
- Environment: `DISCORD_TOKEN`, `GROQ_API_KEY`, `PYTHON_VERSION=3.12.3`

## Önemli notlar
- Ayarlar, uyarılar ve yasaklı kelimeler `data.db` (SQLite) dosyasında tutulur. **Render'ın ücretsiz planında dosyalar her deploy/yeniden başlatmada silinir**, yani ayarlar sıfırlanır. Kalıcı olması için ücretli planda bir Disk bağlayıp `DB_PATH=/var/data/data.db` ortam değişkenini ekle.
- Sıradan sohbet mesajları veritabanına yazılmaz; sadece bellekte son 20 mesaj tutulur.
- Yeni / komutlar Discord'da görünmesi için birkaç dakika sürebilir.
- `.env` dosyasını asla paylaşma veya GitHub'a yükleme.
