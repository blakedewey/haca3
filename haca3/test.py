import sys
import argparse
import torch
import nibablel as nib
import os
import numpy as np
from torchvision.transforms import ToTensor, CencerCrop, Compose, ToPILImage
from modules.model import HACA3


def normalize_intensity(image):
    thresh = np.percentile(image.flatten(), 99)
    image = np.clip(image, a_min=0.0, a_max=thresh)
    image = image / thresh
    return image, thresh


def obtain_single_image(image_path):
    image_obj = nib.load(image_path)
    image_vol = np.array(image_obj.get_fdata().astype(np.float32))
    image_vol, norm_val = normalize_intensity(image_vol)

    n_row, n_col, n_slc = image_vol.shape
    # zero padding
    image_padded = np.zeros((224, 224, 224)).astype(np.float32)
    image_padded[112 - n_row // 2:112 + n_row // 2 + n_row % 2,
    112 - n_col // 2:112 + n_col // 2 + n_col % 2,
    112 - n_slc // 2:112 + n_slc // 2 + n_slc % 2] = image_vol
    return ToTensor()(image_padded), image_obj.affine, image_obj.header, norm_val

def load_source_images(image_paths):
    source_images = []
    contrast_dropout = np.ones((4,)).astype(np.float32) * 1e5
    for contrast_id, image_path in enumerate(image_paths):
        if image_path is not None:
            image_vol, image_affine, image_header, _ = obtain_single_image(image_path)
            contrast_dropout[contrast_id] = 0.0
        else:
            image_vol = ToTensor()(np.ones((224, 224, 224)).astype(np.float32))
        source_images.append(image_vol.float().permute(2, 1, 0))
    return source_images, contrast_dropout, image_affine, image_header

def parse_array(arg_str):
    return np.array([float(x) for x in arg_str.split(',')])


def main(args=None):
    args = sys.argv[1:] if args is None else args
    parser = argparse.ArgumentParser(description='Harmonization with HACA3.')
    parser.add_argument('--t1', type=str, default=None)
    parser.add_argument('--t2', type=str, default=None)
    parser.add_argument('--pd', type=str, default=None)
    parser.add_argument('--flair', type=str, default=None)
    parser.add_argument('--target-image', type=str, nargs='+', default=None)
    parser.add_argument('--target-theta', type=str, default=None)
    parser.add_argument('--target-eta', type=str, default='0.3,0.5')
    parser.add_argument('--out-dir', type=str, default='.')
    parser.add_argument('--file-name', type=str, default='testing_subject.nii.gz')
    parser.add_argument('--gpu-id', type=int, default=0)
    parser.add_argument('--num-batches', type=int, default=4)
    parser.add_argument('--save-intermediate', action='store_true', default=False)
    parser.add_argument('--pretrained-fusion', type=str, default=None)
    args = parser.parse_args(args)

    text_div = '=' * 10
    print(f'{text_div} BEGIN HACA3 HARMONIZATION {text_div}')

    # ==== CHECK CONDITIONS OF INPUT ARGUMENTS ====
    if args.t1 is None and args.t2 is None and args.pd is None and args.flair is None:
        parser.error("At least one source image must be provided.")

    if args.target_image is None and args.target_theta is None:
        parser.error("Target image OR target theta value should be provided.")

    if args.target_image is not None and args.target_theta is not None:
        print('Warning: Both "target_image" and "target_theta" are provided. Only "target_image" will be used...')

    # ==== INITIALIZE MODEL ====
    haca3 = HACA3(beta_dim=5,
                  theta_dim=2,
                  eta_dim=2,
                  pretrained_harmonization=args.pretrained_harmonization,
                  gpu=args.gpu_id)

    # ==== LOAD SOURCE IMAGES ====
    source_images, contrast_dropout, image_affine, image_header = load_source_images([args.t1, args.t2, args.pd, args.flair])

    # ==== LOAD TARGET IMAGES IF PROVIDED ====
    if args.target_image is not None:
        contrast_names = ["T1", "T2", "PD", "FLAIR"]
        target_images, target_contrasts, norm_vals = [], [], []
        for target_image_path in args.target_image:
            target_contrasts.append([t for t in contrast_names if t in target_image_path][0])
            target_image_tmp, _, _, norm_val = obtain_single_image(target_image_path)
            target_images.append(target_image_tmp.permute(2, 1, 0).permute(0, 2, 1).flip(1)[100:120, ...])
            norm_vals.append(norm_val)
    else:
        target_images = None
        target_theta = parse_array(args.target_theta)
        target_eta = parse_array(args.target_eta)

    # ===== BEGIN HARMONIZATION WITH HACA3 =====
    # Axial
    haca3.harmonize(source_images=[image.permute(2, 0, 1) for image in source_images],
                    target_images=target_images,
                    target_theta=torch.from_numpy(target_theta),
                    target_eta=torch.from_numpy(target_eta),
                    target_contrasts=target_contrasts,
                    contrast_dropout=torch.from_numpy(contrast_dropout),
                    out_dir=args.out_dir,
                    file_name=args.file_name,
                    recon_orientation='axial',
                    affine=image_affine,
                    header=image_header,
                    num_batches=args.num_batches,
                    save_intermediate=args.save_intermediate,
                    norm_val=norm_vals)


