if (!customElements.get('media-gallery')) {
  customElements.define(
    'media-gallery',
    class MediaGallery extends HTMLElement {
      constructor() {
        super();
        this.elements = {
          liveRegion: this.querySelector('[id^="GalleryStatus"]'),
          viewer: this.querySelector('[id^="GalleryViewer"]'),
          thumbnails: this.querySelector('[id^="GalleryThumbnails"]'),
        };
        this.mql = window.matchMedia('(min-width: 750px)');
        if (!this.elements.thumbnails) return;

        this.elements.viewer.addEventListener('slideChanged', debounce(this.onSlideChanged.bind(this), 500));
        this.elements.thumbnails.querySelectorAll('[data-target]').forEach((mediaToSwitch) => {
          mediaToSwitch
            .querySelector('button')
            .addEventListener('click', this.setActiveMedia.bind(this, mediaToSwitch.dataset.target, false));
        });
        if (this.dataset.desktopLayout.includes('thumbnail') && this.mql.matches) this.removeListSemantic();
      }

      connectedCallback() {
        // product-info can initialize before this custom element is upgraded.
        // Apply initial media filtering here so first render is color-scoped.
        window.requestAnimationFrame(() => {
          this.applyVariantMediaFilter();
        });
      }

      getSelectedColor(variant) {
        const selectedOptions = variant?.selectedOptions || [];
        const colorOption = selectedOptions.find(
          (option) => String(option?.name || '').toLowerCase() === 'color'
        );
        if (colorOption) return String(colorOption.value || '').trim();

        const colorOptionPosition = Number.parseInt(this.dataset.colorOptionPosition || '0', 10);
        if (colorOptionPosition > 0) {
          const zeroBased = colorOptionPosition - 1;
          if (Array.isArray(variant?.options) && variant.options[zeroBased]) {
            return String(variant.options[zeroBased]).trim();
          }
          const optionKey = `option${colorOptionPosition}`;
          if (variant?.[optionKey]) {
            return String(variant[optionKey]).trim();
          }
        }

        // Fallback to current picker state for themes that don't expose selected options in JSON.
        const productInfo = this.closest('product-info') || document;
        const checkedColor = productInfo.querySelector('input[type="radio"][name*="Color"]:checked');
        if (checkedColor?.value) return String(checkedColor.value).trim();
        const selectColor = productInfo.querySelector('select[name*="Color"]');
        if (selectColor?.value) return String(selectColor.value).trim();

        return '';
      }

      getColorFromMediaAlt(altText) {
        const normalized = String(altText || '').trim();
        const match = normalized.match(/\s-\s([^\-]+?)\s\((front|back)\)\s*$/i);
        return match ? match[1].trim() : '';
      }

      applyVariantMediaFilter(variant) {
        let selectedColor = this.getSelectedColor(variant).toLowerCase();
        if (!this.elements.viewer) return;

        const viewerItems = Array.from(this.elements.viewer.querySelectorAll('li[data-media-id]'));
        if (!viewerItems.length) return;

        // Initial page load can happen before picker state is hydrated; infer from active media.
        if (!selectedColor) {
          const activeItem = this.elements.viewer.querySelector('li[data-media-id].is-active[data-media-alt]');
          const activeColor = this.getColorFromMediaAlt(activeItem?.dataset?.mediaAlt || '').toLowerCase();
          if (activeColor) selectedColor = activeColor;
        }

        const visibilityByMediaId = new Map();
        viewerItems.forEach((item) => {
          const mediaColor = this.getColorFromMediaAlt(item.dataset.mediaAlt).toLowerCase();
          // If a media alt doesn't follow the uploader naming format, keep it visible.
          const isVisible = !selectedColor || !mediaColor || mediaColor === selectedColor;
          item.hidden = !isVisible;
          item.classList.toggle('hidden', !isVisible);
          visibilityByMediaId.set(item.dataset.mediaId, isVisible);
        });

        if (this.elements.thumbnails) {
          const thumbnailItems = Array.from(this.elements.thumbnails.querySelectorAll('[data-target]'));
          thumbnailItems.forEach((item) => {
            const isVisible = visibilityByMediaId.get(item.dataset.target) ?? true;
            item.hidden = !isVisible;
            item.classList.toggle('hidden', !isVisible);
          });
        }

        if (this.elements.viewer.slider) this.elements.viewer.resetPages();
        if (this.elements.thumbnails?.slider) this.elements.thumbnails.resetPages();

        const activeVisible = this.elements.viewer.querySelector('li[data-media-id].is-active:not([hidden])');
        if (activeVisible) return;

        const firstVisible = this.elements.viewer.querySelector('li[data-media-id]:not([hidden])');
        if (firstVisible) this.setActiveMedia(firstVisible.dataset.mediaId, false);
      }

      onSlideChanged(event) {
        const thumbnail = this.elements.thumbnails.querySelector(
          `[data-target="${event.detail.currentElement.dataset.mediaId}"]`
        );
        this.setActiveThumbnail(thumbnail);
      }

      setActiveMedia(mediaId, prepend) {
        const activeMedia =
          this.elements.viewer.querySelector(`[data-media-id="${mediaId}"]`) ||
          this.elements.viewer.querySelector('[data-media-id]');
        if (!activeMedia) {
          return;
        }
        this.elements.viewer.querySelectorAll('[data-media-id]').forEach((element) => {
          element.classList.remove('is-active');
        });
        activeMedia?.classList?.add('is-active');

        if (prepend) {
          activeMedia.parentElement.firstChild !== activeMedia && activeMedia.parentElement.prepend(activeMedia);

          if (this.elements.thumbnails) {
            const activeThumbnail = this.elements.thumbnails.querySelector(`[data-target="${mediaId}"]`);
            activeThumbnail.parentElement.firstChild !== activeThumbnail && activeThumbnail.parentElement.prepend(activeThumbnail);
          }

          if (this.elements.viewer.slider) this.elements.viewer.resetPages();
        }

        this.preventStickyHeader();
        window.setTimeout(() => {
          if (!this.mql.matches || this.elements.thumbnails) {
            activeMedia.parentElement.scrollTo({ left: activeMedia.offsetLeft });
          }
          const activeMediaRect = activeMedia.getBoundingClientRect();
          // Don't scroll if the image is already in view
          if (activeMediaRect.top > -0.5) return;
          const top = activeMediaRect.top + window.scrollY;
          window.scrollTo({ top: top, behavior: 'smooth' });
        });
        this.playActiveMedia(activeMedia);

        if (!this.elements.thumbnails) return;
        const activeThumbnail = this.elements.thumbnails.querySelector(`[data-target="${mediaId}"]`);
        this.setActiveThumbnail(activeThumbnail);
        this.announceLiveRegion(activeMedia, activeThumbnail.dataset.mediaPosition);
      }

      setActiveThumbnail(thumbnail) {
        if (!this.elements.thumbnails || !thumbnail) return;

        this.elements.thumbnails
          .querySelectorAll('button')
          .forEach((element) => element.removeAttribute('aria-current'));
        thumbnail.querySelector('button').setAttribute('aria-current', true);
        if (this.elements.thumbnails.isSlideVisible(thumbnail, 10)) return;

        this.elements.thumbnails.slider.scrollTo({ left: thumbnail.offsetLeft });
      }

      announceLiveRegion(activeItem, position) {
        const image = activeItem.querySelector('.product__modal-opener--image img');
        if (!image) return;
        image.onload = () => {
          this.elements.liveRegion.setAttribute('aria-hidden', false);
          this.elements.liveRegion.innerHTML = window.accessibilityStrings.imageAvailable.replace('[index]', position);
          setTimeout(() => {
            this.elements.liveRegion.setAttribute('aria-hidden', true);
          }, 2000);
        };
        image.src = image.src;
      }

      playActiveMedia(activeItem) {
        window.pauseAllMedia();
        const deferredMedia = activeItem.querySelector('.deferred-media');
        if (deferredMedia) deferredMedia.loadContent(false);
      }

      preventStickyHeader() {
        this.stickyHeader = this.stickyHeader || document.querySelector('sticky-header');
        if (!this.stickyHeader) return;
        this.stickyHeader.dispatchEvent(new Event('preventHeaderReveal'));
      }

      removeListSemantic() {
        if (!this.elements.viewer.slider) return;
        this.elements.viewer.slider.setAttribute('role', 'presentation');
        this.elements.viewer.sliderItems.forEach((slide) => slide.setAttribute('role', 'presentation'));
      }
    }
  );
}
