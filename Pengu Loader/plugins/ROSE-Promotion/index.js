/**
 * @name ROSE-Promotion
 * @author Rose Team
 * @description Injects a custom Challenger promotion celebration overlay using video assets.
 * @version 1.1.0
 */
(function initRosePromotion() {
    const LOG_PREFIX = "[ROSE-Promotion]";

    const log = {
        info: (msg, extra) => console.info(`${LOG_PREFIX} ${msg}`, extra ?? ""),
        warn: (msg, extra) => console.warn(`${LOG_PREFIX} ${msg}`, extra ?? ""),
        error: (msg, extra) => console.error(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    };

    // Assets - CDN URLs (fallback since local paths not working)
    const ASSETS = {
        bg: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-navigation/global/default/eog_looping_bgmagic.webm",
        intro: {
            video: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/videos/ranked/tier-promotion-from-unranked.webm",
            audio: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/sounds/ranked/sfx-tier-wings-promotion-from-unranked.ogg"
        },
        challenger: {
            video: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/videos/ranked/tier-promotion-to-challenger.webm",
            audio: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/sounds/ranked/sfx-tier-wings-promotion-to-challenger.ogg"
        },
        button: {
            hover: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-uikit/global/default/sounds/sfx-uikit-button-gold-hover.ogg",
            click: "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-uikit/global/default/sounds/sfx-uikit-button-gold-click.ogg"
        }
    };

    /**
     * Fetches current summoner info from LCU
     */
    async function getSummonerInfo() {
        try {
            const resp = await fetch('/lol-summoner/v1/current-summoner');
            if (!resp.ok) return null;
            return await resp.json();
        } catch (e) {
            log.warn("Failed to fetch summoner info", e);
            return null;
        }
    }

    /**
     * Creates the user profile display element
     */
    function createProfileDisplay(summoner) {
        const container = document.createElement('div');
        container.id = 'rose-promotion-profile';
        container.style.cssText = `
            position: absolute;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            flex-direction: column;
            align-items: center;
            z-index: 10;
            opacity: 0;
            transition: opacity 1s ease-out 0.5s;
        `;

        // Avatar
        const avatar = document.createElement('img');
        avatar.src = `/lol-game-data/assets/v1/profile-icons/${summoner.profileIconId}.jpg`;
        avatar.style.cssText = `
            width: 80px;
            height: 80px;
            border-radius: 50%;
            border: 3px solid #c8aa6e;
            box-shadow: 0 0 20px rgba(200, 170, 110, 0.5);
            margin-bottom: 12px;
        `;

        // Name
        const name = document.createElement('div');
        name.textContent = summoner.displayName || summoner.gameName || 'Summoner';
        name.style.cssText = `
            font-family: 'LoL Display', 'Beaufort for LOL', serif;
            font-size: 24px;
            font-weight: bold;
            color: #c8aa6e;
            text-shadow: 0 0 10px rgba(200, 170, 110, 0.8);
            text-transform: uppercase;
            letter-spacing: 2px;
        `;

        // Rank text
        const rankText = document.createElement('div');
        rankText.textContent = 'CHALLENGER';
        rankText.style.cssText = `
            font-family: 'LoL Display', 'Beaufort for LOL', serif;
            font-size: 18px;
            font-weight: bold;
            color: #f0e6d3;
            text-shadow: 0 0 15px rgba(255, 215, 0, 0.6);
            margin-top: 8px;
            letter-spacing: 4px;
        `;

        container.appendChild(avatar);
        container.appendChild(name);
        container.appendChild(rankText);

        return container;
    }

    /**
     * Creates and displays the promotion video overlay sequence
     */
    async function showPromotionOverlay() {
        log.info(`Showing promotion overlay sequence...`);

        // 1. Remove existing overlay if any
        const existing = document.getElementById('rose-promotion-overlay');
        if (existing) existing.remove();

        // 2. Create Overlay Container
        const overlay = document.createElement('div');
        overlay.id = 'rose-promotion-overlay';
        overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: #000;
      z-index: 99999; /* Topmost */
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer; /* Click to dismiss */
      animation: fadeIn 0.5s ease-out;
    `;

        // 3. Create Background Video
        const bgVideo = document.createElement('video');
        bgVideo.src = ASSETS.bg;
        bgVideo.style.cssText = `
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0.6; /* Slight dim for focus on main content */
      z-index: 1;
    `;
        bgVideo.autoplay = true;
        bgVideo.loop = true;
        bgVideo.muted = true;

        // 4. Create Main Media Elements
        const mainVideo = document.createElement('video');
        mainVideo.style.cssText = `
      width: 100%;
      height: 100%;
      object-fit: cover;
      position: relative;
      opacity: 0;
      transform: scale(1.05);
      transition: opacity 0.8s ease-out, transform 0.8s ease-out;
      z-index: 2; /* Above BG */
    `;
        mainVideo.autoplay = true;
        mainVideo.controls = false;
        mainVideo.muted = false;

        let currentAudio = null;

        // Helper to play a segment
        function playSegment(assetKey) {
            const assets = ASSETS[assetKey];
            if (!assets) return Promise.resolve();

            return new Promise((resolve) => {
                // Update video source
                mainVideo.src = assets.video;
                mainVideo.load();

                // Play new audio
                if (currentAudio) {
                    currentAudio.pause();
                    currentAudio.remove();
                }
                currentAudio = new Audio(assets.audio);
                currentAudio.volume = 0.6;

                // Handle end of this segment
                const onEnded = () => {
                    mainVideo.onended = null;
                    resolve();
                };
                mainVideo.onended = onEnded;

                // Start playback
                const playPromise = mainVideo.play();
                if (playPromise !== undefined) {
                    playPromise.then(() => {
                        currentAudio.play().catch(e => log.warn("Audio play failed", e));
                    }).catch(e => {
                        log.warn("Video play failed", e);
                        resolve();
                    });
                }
            });
        }

        // 5. Close/Dismiss Logic
        function closeOverlay() {
            log.info("Closing overlay...");
            overlay.style.transition = "opacity 0.5s ease";
            overlay.style.opacity = "0";

            if (currentAudio) {
                // Fade out audio
                const audioFade = setInterval(() => {
                    if (currentAudio.volume > 0.05) {
                        currentAudio.volume -= 0.05;
                    } else {
                        currentAudio.pause();
                        clearInterval(audioFade);
                    }
                }, 50);
            }

            setTimeout(() => {
                overlay.remove();
                if (currentAudio) {
                    currentAudio.pause();
                    currentAudio.remove();
                }
            }, 500);

            isClosed = true;
        }

        let isClosed = false;
        // Remove click-to-close on overlay
        // overlay.onclick = closeOverlay;

        // --- UI Construction ---

        // 1. Header (Top Text)
        const header = document.createElement('div');
        header.style.cssText = `
            position: absolute;
            top: 15%; /* Adjusted position */
            left: 50%;
            transform: translateX(-50%);
            text-align: center;
            opacity: 0;
            transition: opacity 1s ease;
            z-index: 20;
        `;

        const title = document.createElement('div');
        title.textContent = 'PROMOTED TO CHALLENGER';
        title.style.cssText = `
            font-family: 'Beaufort for LOL', serif;
            font-size: 32px;
            font-weight: 700;
            color: #f0e6d2;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 5px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.5);
        `;

        const subtitle = document.createElement('div');
        subtitle.textContent = 'Ranked Solo/Duo';
        subtitle.style.cssText = `
            font-family: 'Spiegel', 'Beaufort for LOL', sans-serif;
            font-size: 14px;
            color: #93856e;
            letter-spacing: 1px;
        `;

        header.appendChild(title);
        header.appendChild(subtitle);
        overlay.appendChild(header);

        // 2. Profile Display (Bottom Center)
        let profileDisplay = null;
        const summoner = await getSummonerInfo();

        if (summoner) {
            profileDisplay = document.createElement('div');
            profileDisplay.style.cssText = `
                position: absolute;
                bottom: 25%;
                left: 50%;
                transform: translateX(-50%);
                display: flex;
                align-items: center;
                gap: 15px;
                opacity: 0;
                transition: opacity 1s ease;
                z-index: 20;
            `;

            const avatar = document.createElement('img');
            avatar.src = `/lol-game-data/assets/v1/profile-icons/${summoner.profileIconId}.jpg`;
            avatar.style.cssText = `
                width: 40px;
                height: 40px;
                border-radius: 50%;
                border: 2px solid #c8aa6e;
                box-shadow: 0 0 10px rgba(0,0,0,0.5);
            `;

            const name = document.createElement('div');
            name.textContent = summoner.displayName || summoner.gameName;
            name.style.cssText = `
                font-family: 'Beaufort for LOL', serif;
                font-size: 18px;
                font-weight: 700;
                color: #f0e6d2;
                letter-spacing: 1px;
                text-shadow: 0 1px 2px rgba(0,0,0,0.8);
            `;

            profileDisplay.appendChild(avatar);
            profileDisplay.appendChild(name);
            overlay.appendChild(profileDisplay);
        }

        // 3. OK Button (Bottom)
        const okWrapper = document.createElement('div');
        okWrapper.style.cssText = `
            position: absolute;
            bottom: 10%;
            left: 50%;
            transform: translateX(-50%);
            opacity: 0;
            transition: opacity 1s ease;
            z-index: 20;
        `;

        const okButton = document.createElement('button');
        okButton.textContent = 'OK';
        okButton.style.cssText = `
            min-width: 150px;
            height: 32px;
            background: #1e2328;
            border: 2px solid #5c5b57;
            color: #cdbe91;
            font-family: 'Beaufort for LOL', serif;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 1px;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 0 1px 1px #010a13;
        `;

        okButton.onmouseenter = () => {
            new Audio(ASSETS.button.hover).play().catch(() => { });
            okButton.style.border = '2px solid #f0e6d2';
            okButton.style.color = '#f0e6d2';
            okButton.style.background = '#1e2328 linear-gradient(to bottom, rgba(30,35,40,1) 0%, rgba(40,45,50,1) 100%)';
        };
        okButton.onmouseleave = () => {
            okButton.style.border = '2px solid #5c5b57';
            okButton.style.color = '#cdbe91';
            okButton.style.background = '#1e2328';
        };
        okButton.onclick = () => {
            new Audio(ASSETS.button.click).play().catch(() => { });
            closeOverlay();
        };

        okWrapper.appendChild(okButton);
        overlay.appendChild(okWrapper);


        // 4. Run Sequence
        // Append elements
        overlay.appendChild(bgVideo);
        overlay.appendChild(mainVideo);
        document.body.appendChild(overlay);

        try {
            // Start BG first
            bgVideo.play().catch(e => log.warn("BG play failed", e));

            // Wait a moment for BG
            await new Promise(r => setTimeout(r, 800));

            // Transition in main video
            mainVideo.style.opacity = "1";
            mainVideo.style.transform = "scale(1)";

            await new Promise(r => setTimeout(r, 300));

            // Play Intro
            if (!isClosed) await playSegment('intro');

            // Play Challenger
            if (!isClosed) await playSegment('challenger');

            // Video sequence finished.
            // DO NOT closeOverlay(). Instead, reveal UI.

            if (!isClosed) {
                // Fade in UI elements
                header.style.opacity = '1';
                if (profileDisplay) profileDisplay.style.opacity = '1';
                okWrapper.style.opacity = '1';

                // Background video is already looping.
                // Main video (video element) holds the last frame by default if we don't clear source.
                // User waits and clicks OK to close.
            }

        } catch (e) {
            log.error("Sequence error:", e);
            closeOverlay();
        }
    }

    // --- Logic ---

    // Flag to prevent double triggering
    let isPromotionShowing = false;

    async function checkAndTriggerPromotion() {
        if (isPromotionShowing) return;

        // Check if we should trigger
        // We trigger when the user "Activates" a skin/profile, which sets 'bgcm-selected-skin-id'
        // This is a simplified heuristic. In a real app we might want a specific 'trigger-promotion' flag.
        // For now, we assume if this value updates, the user likely clicked "Activate".

        // However, to avoid showing it on EVERY startup, we could use a session flag or just show it 
        // when the specific 'challenger' ID is set. 
        // Since the user asked to "assign action to active challenger button", and that button sets the skin ID...
        // We will listen for that specific change.

        // Wait a bit before showing (User request: 1-2s)
        setTimeout(() => {
            if (!isPromotionShowing) {
                isPromotionShowing = true;
                showPromotionOverlay().then(() => {
                    isPromotionShowing = false;
                });
            }
        }, 2000);
    }

    /**
     * Observe DataStore for changes to the selected skin/background.
     * When 'bgcm-selected-skin-id' is set, we assume the user clicked "Activate".
     */
    function initObserver() {
        // 1. Check if we just activated (via flag from Settings Panel)
        if (window.DataStore) {
            try {
                const showPromo = window.DataStore.get('Rose-show-promotion-moment');
                if (showPromo === 'true') {
                    log.info("Promotion flag detected. Triggering sequence...");
                    // Clear flag immediately
                    window.DataStore.remove('Rose-show-promotion-moment');

                    // Trigger with delay
                    checkAndTriggerPromotion();
                }
            } catch (e) {
                log.warn("Failed to check promotion flag", e);
            }
        }

        if (window.DataStore) {
            const originalSet = window.DataStore.set;
            window.DataStore.set = function (key, value) {
                const result = originalSet.apply(this, arguments);
                if (key === 'bgcm-selected-skin-id') {
                    checkAndTriggerPromotion();
                }
                return result;
            };
        }
    }

    // Expose a clean trigger function for other plugins (like Settings Panel) to call directly
    window.ROSE_triggerPromotion = function () {
        checkAndTriggerPromotion();
    };

    // Initialize
    initObserver();

    log.info("Promotion plugin ready.");

})();
